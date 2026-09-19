"""Actions and panels of the editor that act on one sentence of the working text."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import TranslationTextForm
from .glossary import can_propose_term, find_terms, visible_terms
from .memory import MIN_SCORE, other_versions, similar_sentences
from .models import GlossaryEntry, TranslatedSegment
from .services import save_translation, set_sentence_status
from .views import _own_version


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
