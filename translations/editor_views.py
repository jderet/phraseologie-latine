"""Actions and panels of the editor that act on one sentence of the working text."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.limits import ContributionLimitReached, check_text_for_links
from moderation.registry import can_view

from . import qa
from .comments import (
    can_comment_sentence,
    can_resolve,
    comments_for,
    post_sentence_comment,
    set_resolved,
)
from .forms import SentenceCommentForm, TranslationTextForm
from .glossary import can_propose_term, find_terms, visible_terms
from .memory import MIN_SCORE, other_versions, similar_sentences
from .models import GlossaryEntry, IgnoredAlert, SentenceComment, TranslatedSegment
from .sentence_history import sentence_history
from .services import save_translation, set_sentence_status
from .sources import SourceHistory
from .views import _own_version, _rows, _version


def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


def _editor_url(version, segment):
    return f"{reverse('translations:version_edit', args=[version.pk])}#s{segment.pk}"


@login_required
@require_POST
def sentence_status(request, pk, segment_pk):
    """Mark a sentence as a draft, translated or reviewed.

    Without the script of the editor, the whole form is sent here: the Latin of the sentence
    is saved first, so that nothing typed is lost.
    """
    version = _own_version(request.user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    status = request.POST.get("status", "")
    if status not in TranslatedSegment.Status.values:
        return HttpResponseBadRequest()
    typed = request.POST.get(f"s{segment.pk}")
    if typed is not None:
        form = TranslationTextForm({"text": typed}, user=request.user)
        if form.is_valid():
            save_translation(version, segment, form.cleaned_data["text"], request.user)
    try:
        set_sentence_status(version, segment, status, request.user)
    except ValidationError as error:
        if _wants_json(request):
            return JsonResponse({"errors": error.messages}, status=400)
        messages.error(request, error.messages[0])
        return redirect(_editor_url(version, segment))
    if _wants_json(request):
        return JsonResponse({"status": status})
    return redirect(_editor_url(version, segment))


@login_required
@require_GET
def memory_panel(request, pk, segment_pk):
    """The Latin already written for this sentence in the other versions of the project, then
    for similar sentences: a fragment of the side panel of the editor."""
    version = _own_version(request.user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    return render(
        request,
        "translations/panel_memory.html",
        {
            "version": version,
            "segment": segment,
            "others": other_versions(request.user, version, segment),
            "matches": similar_sentences(request.user, version, segment),
            "min_score": MIN_SCORE,
        },
    )


@login_required
@require_GET
def glossary_panel(request, pk, segment_pk):
    """Terms of the glossary found in the sentence: adopted ones, then proposed ones."""
    version = _own_version(request.user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    terms = visible_terms(
        request.user,
        version.project,
        (GlossaryEntry.Status.ADOPTED, GlossaryEntry.Status.PROPOSED),
    )
    found = []
    for item in find_terms(segment.text, terms):
        if item.entry not in found:
            found.append(item.entry)
    return render(
        request,
        "translations/panel_glossary.html",
        {
            "version": version,
            "project": version.project,
            "entries": found,
            "can_propose": can_propose_term(request.user, version.project),
        },
    )


def _comment_target(user, pk, segment_pk):
    """A version the user may see and one of its current sentences."""
    version = _version(user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    return version, segment


@require_GET
def comments_panel(request, pk, segment_pk):
    """The comments of a sentence and the form to add one, for the side panel."""
    version, segment = _comment_target(request.user, pk, segment_pk)
    comments = comments_for(request.user, version, segment)
    for comment in comments:
        comment.can_resolve = can_resolve(request.user, comment)
    return render(
        request,
        "translations/panel_comments.html",
        {
            "version": version,
            "segment": segment,
            "comments": comments,
            "can_comment": can_comment_sentence(request.user, version),
            "form": SentenceCommentForm(),
        },
    )


@login_required
@require_POST
def comment_post(request, pk, segment_pk):
    version, segment = _comment_target(request.user, pk, segment_pk)
    form = SentenceCommentForm(request.POST)
    if not form.is_valid():
        return _comment_answer(request, version, segment, error=_("Écrivez un commentaire."))
    try:
        check_text_for_links(request.user, form.cleaned_data["text"])
        post_sentence_comment(version, segment, request.user, form.cleaned_data["text"])
    except (ValidationError, ContributionLimitReached) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else str(error)
        return _comment_answer(request, version, segment, error=message)
    return _comment_answer(request, version, segment)


@login_required
@require_POST
def comment_resolve(request, pk):
    comment = get_object_or_404(SentenceComment.objects.select_related("version"), pk=pk)
    if not can_view(request.user, comment):
        raise Http404
    set_resolved(comment, request.user, request.POST.get("resolu") == "1")
    return _comment_answer(request, comment.version, comment.segment)


def _comment_answer(request, version, segment, error=None):
    """JSON for the editor; otherwise back to the page the form came from."""
    if _wants_json(request):
        if error:
            return JsonResponse({"errors": [error]}, status=400)
        return JsonResponse({"ok": True})
    if error:
        messages.error(request, error)
    else:
        messages.success(request, _("C’est enregistré."))
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("translations:version_comments", args=[version.pk])
    return redirect(back)


@require_GET
def version_comments(request, pk):
    """All the comments of a version, sentence by sentence."""
    version = _version(request.user, pk)
    comments = comments_for(request.user, version)
    history = SourceHistory(version.project.source_text)
    numbers = history.numbers_at()
    for comment in comments:
        comment.number = numbers.get(comment.segment.latest.pk)
        comment.can_resolve = can_resolve(request.user, comment)
    comments.sort(key=lambda comment: (comment.number or 0, comment.created_at))
    sentences = list(enumerate(history.segments_at(), start=1))
    asked = request.GET.get("phrase", "")
    return render(
        request,
        "translations/version_comments.html",
        {
            "version": version,
            "project": version.project,
            "comments": comments,
            "sentences": sentences,
            "asked": int(asked) if asked.isdigit() else None,
            "can_comment": can_comment_sentence(request.user, version),
            "form": SentenceCommentForm(),
        },
    )


@login_required
@require_POST
def comment_post_by_number(request, pk):
    """Comment a sentence chosen by its number, from the page of the comments."""
    version = _version(request.user, pk)
    number = request.POST.get("phrase", "")
    segments = SourceHistory(version.project.source_text).segments_at()
    if not number.isdigit() or not 1 <= int(number) <= len(segments):
        return HttpResponseBadRequest()
    return comment_post(request, pk, segments[int(number) - 1].pk)


@login_required
@require_GET
def history_panel(request, pk, segment_pk):
    """The Latin of the sentence at each step, for the side panel of the editor."""
    version = _own_version(request.user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    entries = sentence_history(request.user, version, segment)
    current = entries[0].text if entries else ""
    return render(
        request,
        "translations/panel_history.html",
        {"version": version, "segment": segment, "entries": entries, "current": current},
    )


@login_required
@require_POST
def sentence_restore(request, pk, segment_pk):
    """Put back in the working text the Latin a step gave to the sentence."""
    version = _own_version(request.user, pk)
    segment = get_object_or_404(version.project.source_text.segments.current(), pk=segment_pk)
    number = request.POST.get("etape", "")
    entry = next(
        (
            entry
            for entry in sentence_history(request.user, version, segment)
            if entry.step is not None and str(entry.step.number) == number
        ),
        None,
    )
    if entry is None:
        return HttpResponseBadRequest()
    save_translation(version, segment, entry.text, request.user, written_by=entry.written_by)
    if _wants_json(request):
        return JsonResponse({"text": entry.text})
    messages.success(request, _("Le texte de l’étape est rétabli dans le texte de travail."))
    return redirect(_editor_url(version, segment))


@login_required
@require_http_methods(["GET", "POST"])
def quality_report(request, pk):
    """Every alert of the quality checks on the working text; an alert may be ignored for the
    current Latin of its sentence."""
    version = _own_version(request.user, pk)
    _step, rows = _rows(request.user, version)
    if request.method == "POST":
        code = request.POST.get("code", "")
        row = next(
            (row for row in rows if str(row["segment"].pk) == request.POST.get("phrase")), None
        )
        if row is None or code not in qa.LABELS or not row["saved"]:
            return HttpResponseBadRequest()
        IgnoredAlert.objects.get_or_create(
            version=version,
            segment=row["segment"],
            code=code,
            fingerprint=qa.fingerprint(row["saved"]),
            defaults={"ignored_by": request.user},
        )
        messages.success(request, _("L’alerte est ignorée tant que cette phrase ne change pas."))
        return redirect(f"{request.path}#phrase-{row['number']}")
    terms = visible_terms(request.user, version.project)
    alerts = qa.check_rows(rows, terms, qa.ignored_alerts(version))
    flagged = [
        dict(row, alerts=alerts[row["segment"].pk]) for row in rows if row["segment"].pk in alerts
    ]
    return render(
        request,
        "translations/quality_report.html",
        {
            "version": version,
            "project": version.project,
            "rows": flagged,
            "checked": sum(1 for row in rows if row["saved"]),
            "ignored_count": version.ignored_alerts.count(),
        },
    )


@login_required
@require_POST
def quality_reset(request, pk):
    """Show again every alert that was ignored."""
    version = _own_version(request.user, pk)
    version.ignored_alerts.all().delete()
    messages.success(request, _("Les alertes ignorées sont de nouveau montrées."))
    return redirect("translations:quality_report", version.pk)
