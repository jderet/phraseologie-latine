from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from corpus.models import Token
from corpus.search import quotation
from corpus.views import search_context
from moderation.registry import can_view
from translations.models import TranslatedSegment, TranslationVersion
from translations.permissions import can_translate

from .forms import JustificationForm, ReferenceFormSet
from .models import Evidence, Justification
from .services import (
    add_evidences,
    corpus_evidence,
    create_justification,
    update_justification,
    withdraw_evidence,
)

SEARCH_RESULTS = 20
FORM_TEMPLATE = "justifications/justification_form.html"


def _hint(request):
    value = request.POST.get("debut") or request.GET.get("debut") or ""
    return int(value) if value.isdigit() else None


def _attestations(request):
    """Attestations ticked in the form, and the errors of those that are not valid."""
    evidences, errors = [], []
    if request.method != "POST":
        return evidences, errors
    for value in dict.fromkeys(request.POST.getlist("attestation")):
        try:
            evidences.append(corpus_evidence(value))
        except ValidationError as error:
            errors.extend(error.messages)
    return evidences, errors


def _references(request):
    data = request.POST if request.method == "POST" else None
    return ReferenceFormSet(data, prefix="references", form_kwargs={"user": request.user})


def _reference_evidences(references):
    return [evidence for evidence in (form.evidence() for form in references) if evidence]


def _page_context(translated, **extra):
    return {
        "version": translated.version,
        "segment": translated.segment,
        "translated": translated,
        "source_language": translated.version.project.source_text.language,
        **extra,
    }


def _search_page_context(request, translated, evidences, **extra):
    """The corpus search of the page, and the attestations already ticked."""
    search = search_context(request, SEARCH_RESULTS)
    found = {hit.word_ids for hit in search.get("hits", [])}
    chosen = [quotation(evidence.tokens) for evidence in evidences]
    return _page_context(
        translated,
        search=search,
        chosen=[quote for quote in chosen if quote.word_ids not in found],
        chosen_ids={quote.word_ids for quote in chosen},
        hint=_hint(request),
        **extra,
    )


def _own_version(user, pk):
    version = get_object_or_404(
        TranslationVersion.objects.select_related("project__source_text", "author"), pk=pk
    )
    if not can_view(user, version):
        raise Http404
    if not can_translate(user, version):
        raise PermissionDenied
    return version


def _justification(user, pk):
    queryset = Justification.objects.select_related(
        "author",
        "translated_segment__segment",
        "translated_segment__version__project__source_text",
        "translated_segment__version__author",
    )
    justification = get_object_or_404(queryset, pk=pk)
    if not can_view(user, justification):
        raise Http404
    return justification


def _own_justification(user, pk):
    justification = _justification(user, pk)
    if user.pk != justification.author_id:
        raise PermissionDenied
    return justification


@login_required
@require_http_methods(["GET", "POST"])
def justification_create(request, version_pk, segment_pk):
    version = _own_version(request.user, version_pk)
    source_segment = get_object_or_404(version.project.source_text.segments, pk=segment_pk)
    translated = (
        TranslatedSegment.objects.filter(version=version, segment=source_segment)
        .exclude(text="")
        .first()
    )
    if translated is None:
        messages.error(request, _("Traduisez et enregistrez d’abord cette phrase."))
        return redirect("translations:version_edit", version.pk)
    translated.version, translated.segment = version, source_segment

    form = JustificationForm(
        request.POST or None,
        translated=translated,
        user=request.user,
        initial={"latin_excerpt": request.GET.get("extrait", "")},
    )
    references = _references(request)
    evidences, errors = _attestations(request)
    if request.method == "POST":
        valid = form.is_valid() & references.is_valid()
        for message in errors:
            form.add_error(None, message)
        if valid and not errors:
            justification = form.save(commit=False)
            justification.translated_segment = translated
            all_evidences = evidences + _reference_evidences(references)
            try:
                create_justification(justification, request.user, all_evidences, _hint(request))
            except ContributionLimitReached as error:
                messages.error(request, str(error))
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, _("La justification est enregistrée."))
                return redirect(justification)
    keep = {key: request.GET[key] for key in ("extrait", "debut") if request.GET.get(key)}
    context = _search_page_context(
        request,
        translated,
        evidences,
        form=form,
        references=references,
        keep=keep,
        heading=_("Justifier un choix de traduction"),
        submit_label=_("Enregistrer la justification"),
        show_rules=True,
    )
    return render(request, FORM_TEMPLATE, context)


def justification_detail(request, pk):
    justification = _justification(request.user, pk)
    translated = justification.translated_segment
    tokens = Token.objects.select_related("passage__edition__work__author")
    queryset = (
        justification.evidences.filter(is_withdrawn=False)
        .select_related("work")
        .prefetch_related(Prefetch("tokens", queryset=tokens))
    )
    evidences = []
    for evidence in queryset:
        evidence.justification = justification
        if not can_view(request.user, evidence):
            continue
        if evidence.kind == Evidence.Kind.CORPUS and evidence.tokens.all():
            evidence.quotation = quotation(list(evidence.tokens.all()))
        evidences.append(evidence)
    span = justification.locate()
    text = translated.text
    parts = (text[: span[0]], text[span[0] : span[1]], text[span[1] :]) if span else None
    return render(
        request,
        "justifications/justification_detail.html",
        _page_context(
            translated,
            justification=justification,
            evidences=evidences,
            parts=parts,
            can_edit=request.user.pk == justification.author_id,
        ),
    )


@login_required
@require_http_methods(["GET", "POST"])
def justification_edit(request, pk):
    justification = _own_justification(request.user, pk)
    translated = justification.translated_segment
    hint = justification.latin_start
    form = JustificationForm(
        request.POST or None, instance=justification, translated=translated, user=request.user
    )
    if request.method == "POST" and form.is_valid():
        try:
            revision = update_justification(form.save(commit=False), request.user, hint)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if revision is None:
                messages.info(request, _("Aucune modification."))
            else:
                messages.success(request, _("Les modifications sont enregistrées."))
            return redirect(justification)
    context = _page_context(
        translated,
        form=form,
        justification=justification,
        heading=_("Modifier la justification"),
        submit_label=_("Enregistrer"),
        show_rules=True,
    )
    return render(request, FORM_TEMPLATE, context)


@login_required
@require_http_methods(["GET", "POST"])
def evidence_add(request, pk):
    justification = _own_justification(request.user, pk)
    translated = justification.translated_segment
    references = _references(request)
    evidences, errors = _attestations(request)
    if request.method == "POST" and references.is_valid() and not errors:
        new_evidences = evidences + _reference_evidences(references)
        if new_evidences:
            add_evidences(justification, new_evidences, request.user)
            count = len(new_evidences)
            messages.success(
                request,
                ngettext("%(count)d preuve ajoutée.", "%(count)d preuves ajoutées.", count)
                % {"count": count},
            )
            return redirect(justification)
        errors = [_("Cochez une attestation ou citez un ouvrage.")]
    context = _search_page_context(
        request,
        translated,
        evidences,
        references=references,
        justification=justification,
        errors=errors,
        keep={},
        heading=_("Ajouter des preuves"),
        submit_label=_("Ajouter les preuves"),
    )
    return render(request, FORM_TEMPLATE, context)


@login_required
@require_POST
def evidence_withdraw(request, pk):
    evidence = get_object_or_404(Evidence, pk=pk)
    justification = _own_justification(request.user, evidence.justification_id)
    evidence.justification = justification
    try:
        withdraw_evidence(evidence, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _("La preuve est retirée."))
    return redirect(justification)
