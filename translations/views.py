import datetime as dt
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from corpus.forms import MODE_FORM, SCOPE_CORE, SearchForm
from justifications.display import visible_evidences
from justifications.models import Challenge, Justification
from moderation.registry import can_view
from moderation.services import save_with_revision

from .diffs import word_diff
from .exports import bilingual_text, export_filename
from .forms import (
    ProjectForm,
    PublishForm,
    ReferenceForm,
    SourceTextEditForm,
    SourceTextForm,
    StepForm,
    TranslationTextForm,
    VersionForm,
)
from .models import SourceText, TranslationProject, TranslationVersion, is_version_author
from .permissions import can_challenge, can_copy, can_edit, can_translate
from .segmentation import from_lines, segment, to_lines
from .services import (
    copy_version,
    create_project,
    create_source_text,
    create_step,
    create_version,
    publish_version,
    save_translation,
    set_reference_version,
)
from .steps import (
    latest_step,
    pending_changes,
    public_step,
    shown_sentences,
    step_sentences,
    waiting_justifications,
)

ITEMS_PER_PAGE = 50
# Value of the comparison parameter that designates the working text of the author.
WORKING_TEXT = "travail"
PANEL_SEARCH_DEFAULTS = {"scope": SCOPE_CORE, "mode1": MODE_FORM, "mode2": MODE_FORM}


def _visible(user, queryset, pk):
    obj = get_object_or_404(queryset, pk=pk)
    if not can_view(user, obj):
        raise Http404
    return obj


def _paginate(request, queryset):
    return Paginator(queryset, ITEMS_PER_PAGE).get_page(request.GET.get("page"))


def _contribute(request, save, *args):
    """Run a saving service; a reached limit is shown as a message. Return (result, saved)."""
    try:
        return save(*args), True
    except ContributionLimitReached as error:
        messages.error(request, str(error))
        return None, False


def _saved_message(request, revision):
    if revision is None:
        messages.info(request, _("Aucune modification."))
    else:
        messages.success(request, _("Les modifications sont enregistrées."))


# Source texts


def source_list(request):
    texts = (
        SourceText.objects.filter(is_hidden=False)
        .select_related("added_by")
        .annotate(segment_count=Count("segments"))
        .order_by("-created_at", "-pk")
    )
    return render(request, "translations/source_list.html", {"page": _paginate(request, texts)})


def source_detail(request, pk):
    source = _visible(request.user, SourceText.objects.select_related("added_by"), pk)
    return render(
        request,
        "translations/source_detail.html",
        {
            "source": source,
            "segments": source.segments.all(),
            "projects": source.projects.filter(is_hidden=False).select_related("created_by"),
            "can_edit": can_edit(request.user, source),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_create(request):
    """Adding a text takes two steps: the text is split, then the split is checked and saved."""
    if request.method != "POST":
        form = SourceTextForm(user=request.user)
        return render(request, "translations/source_create.html", {"form": form})
    data = request.POST.copy()
    if data.get("segmented") != "1":
        data["text"] = to_lines(segment(data.get("text", ""), data.get("language", "")))
        form = SourceTextForm(data, user=request.user)
        return render(
            request,
            "translations/source_create.html",
            {"form": form, "segmented": True, "sentences": from_lines(data["text"])},
        )
    form = SourceTextForm(data, user=request.user)
    if form.is_valid():
        source, saved = _contribute(
            request, create_source_text, form.save(commit=False), request.user, form.sentences
        )
        if saved:
            messages.success(request, _("Le texte est ajouté."))
            return redirect(source)
    return render(
        request,
        "translations/source_create.html",
        {"form": form, "segmented": True, "sentences": from_lines(data.get("text", ""))},
    )


@login_required
@require_http_methods(["GET", "POST"])
def source_edit(request, pk):
    source = _visible(request.user, SourceText.objects.all(), pk)
    if not can_edit(request.user, source):
        raise PermissionDenied
    form = SourceTextEditForm(request.POST or None, instance=source, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision, saved = _contribute(
            request, save_with_revision, form.save(commit=False), request.user
        )
        if saved:
            _saved_message(request, revision)
            return redirect(source)
    return render(request, "translations/source_edit.html", {"form": form, "source": source})


# Projects


def project_list(request):
    published = Q(versions__state=TranslationVersion.State.PUBLISHED, versions__is_hidden=False)
    projects = (
        TranslationProject.objects.filter(is_hidden=False, source_text__is_hidden=False)
        .select_related("source_text", "created_by")
        .annotate(published_count=Count("versions", filter=published))
        .order_by("-created_at", "-pk")
    )
    return render(request, "translations/project_list.html", {"page": _paginate(request, projects)})


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request, source_pk):
    source = get_object_or_404(SourceText, pk=source_pk, is_hidden=False)
    form = ProjectForm(request.POST or None, user=request.user, initial={"title": source.title})
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        project.source_text = source
        project, saved = _contribute(request, create_project, project, request.user)
        if saved:
            messages.success(request, _("Le projet est créé."))
            return redirect(project)
    return render(request, "translations/project_form.html", {"form": form, "source": source})


def project_detail(request, pk):
    project = _visible(
        request.user, TranslationProject.objects.select_related("source_text", "created_by"), pk
    )
    versions = list(
        project.versions.visible_to(request.user).select_related(
            "author", "copied_from__version__author"
        )
    )
    for version in versions:
        _step, sentences = shown_sentences(request.user, version)
        version.translated_count = sum(1 for sentence in sentences.values() if sentence.text)
    return render(
        request,
        "translations/project_detail.html",
        {
            "project": project,
            "source": project.source_text,
            "segment_count": project.source_text.segments.count(),
            "published": [version for version in versions if version.is_published],
            "drafts": [version for version in versions if version.is_draft],
            "can_edit": can_edit(request.user, project),
            "reference_id": project.reference_version_id,
            "is_creator": request.user.pk == project.created_by_id,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, pk):
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    if not can_edit(request.user, project):
        raise PermissionDenied
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == "POST" and form.is_valid():
        revision, saved = _contribute(
            request, save_with_revision, form.save(commit=False), request.user
        )
        if saved:
            _saved_message(request, revision)
            return redirect(project)
    return render(
        request,
        "translations/project_form.html",
        {"form": form, "source": project.source_text, "project": project},
    )


@login_required
@require_POST
def project_reference(request, pk):
    project = _visible(request.user, TranslationProject.objects.all(), pk)
    if request.user.pk != project.created_by_id:
        raise PermissionDenied
    form = ReferenceForm(request.POST, project=project)
    if not form.is_valid():
        messages.error(request, _("Choisissez une version publiée de ce projet."))
        return redirect(project)
    version = form.cleaned_data["version"]
    if set_reference_version(project, version, request.user) is None:
        messages.info(request, _("Aucune modification."))
    elif version is None:
        messages.success(request, _("Le projet n’a plus de version de référence."))
    else:
        messages.success(request, _("La version de référence est choisie."))
    return redirect(project)


def project_compare(request, pk):
    """The versions of a project aligned sentence by sentence, the reference version first.

    Each version shows its latest public step; the author's own versions, their working text.
    """
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    versions = sorted(
        project.versions.visible_to(request.user).select_related("author"),
        key=lambda version: (
            version.pk != project.reference_version_id,
            version.is_draft,
            version.published_at or version.created_at,
        ),
    )
    asked = {int(value) for value in request.GET.getlist("v") if value.isdigit()}
    shown = [version for version in versions if version.pk in asked] or versions
    sentences = {version.pk: shown_sentences(request.user, version)[1] for version in shown}
    rows = []
    for source_segment in project.source_text.segments.all():
        cells = []
        for version in shown:
            sentence = sentences[version.pk].get(source_segment.pk)
            cells.append({"version": version, "text": sentence.text if sentence else ""})
        rows.append({"segment": source_segment, "cells": cells})
    return render(
        request,
        "translations/project_compare.html",
        {
            "project": project,
            "source": project.source_text,
            "versions": versions,
            "shown": shown,
            "rows": rows,
            "reference_id": project.reference_version_id,
        },
    )


# Versions


def _version(user, pk):
    queryset = TranslationVersion.objects.select_related(
        "project__source_text", "author", "copied_from__version__author"
    )
    return _visible(user, queryset, pk)


def _own_version(user, pk):
    version = _version(user, pk)
    if not can_translate(user, version):
        raise PermissionDenied
    return version


def _justifications_by_segment(user, version, texts, step=None):
    """Justifications the user may see, read against the Latin shown (``texts`` by segment).

    With a step, only those it or an earlier step brought out.
    """
    grouped = defaultdict(list)
    open_challenges = Challenge.objects.filter(status=Challenge.Status.OPEN, is_hidden=False)
    queryset = (
        Justification.objects.filter(translated_segment__version=version)
        .select_related("translated_segment")
        .prefetch_related(
            Prefetch("challenges", queryset=open_challenges, to_attr="open_challenges")
        )
    )
    if step is not None:
        queryset = queryset.filter(step__number__lte=step.number)
    for justification in queryset:
        translated = justification.translated_segment
        translated.version = version
        justification.shown_text = texts.get(translated.segment_id, "")
        if can_view(user, justification):
            grouped[translated.segment_id].append(justification)
    return grouped


def _challenges_by_segment(user, version):
    grouped = defaultdict(list)
    if version.is_draft:
        return grouped
    queryset = Challenge.objects.filter(
        translated_segment__version=version, status=Challenge.Status.OPEN
    ).select_related("translated_segment")
    for challenge in queryset:
        challenge.translated_segment.version = version
        if can_view(user, challenge):
            grouped[challenge.translated_segment.segment_id].append(challenge)
    return grouped


def _rows(user, version, step=None):
    """The step shown and each sentence of the source text with its Latin and justifications.

    Return (step, rows): the author sees the working text (step None), others the latest
    public step; a step asked shows its own text.
    """
    step, sentences = shown_sentences(user, version, step)
    texts = {segment_id: sentence.text for segment_id, sentence in sentences.items()}
    justifications = _justifications_by_segment(user, version, texts, step)
    challenges = _challenges_by_segment(user, version)
    translated_ids = dict(version.segments.values_list("segment_id", "pk"))
    rows = []
    for source_segment in version.project.source_text.segments.all():
        sentence = sentences.get(source_segment.pk)
        text = sentence.text if sentence else ""
        rows.append(
            {
                "segment": source_segment,
                "translated_pk": translated_ids.get(source_segment.pk),
                "sentence": sentence,
                "saved": text,
                "text": text,
                "errors": None,
                "justifications": justifications.get(source_segment.pk, []),
                "challenges": challenges.get(source_segment.pk, []),
                "origin": _origin(user, version, sentence) if step and sentence else None,
            }
        )
    return step, rows


def _origin(user, version, sentence):
    """The step that last changed a frozen sentence, if the user may see it, and who wrote it."""
    changed_in = sentence.step
    changed_in.version = version
    return {
        "step": changed_in if can_view(user, changed_in) else None,
        "written_by": sentence.written_by,
    }


def _progress(rows):
    return {
        "translated_count": sum(1 for row in rows if row["saved"]),
        "segment_count": len(rows),
    }


def version_detail(request, pk):
    """The author sees the working text; others see the latest public step."""
    user = request.user
    version = _version(user, pk)
    step, rows = _rows(user, version)
    is_author = is_version_author(user, version)
    copy_step = step or public_step(version)
    if copy_step is not None:
        copy_step.version = version
    return render(
        request,
        "translations/version_detail.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            "latest_step": latest_step(version) if is_author else step,
            "pending_count": len(pending_changes(version)) if is_author else 0,
            "waiting_count": waiting_justifications(version).count() if is_author else 0,
            "is_author": is_author,
            "can_translate": can_translate(user, version),
            "is_reference": version.pk == version.project.reference_version_id,
            "can_challenge": step is not None and can_challenge(user, version),
            "copy_step": copy_step if copy_step and can_copy(user, copy_step) else None,
            **_progress(rows),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_create(request, project_pk):
    project = get_object_or_404(TranslationProject, pk=project_pk, is_hidden=False)
    form = VersionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        version = form.save(commit=False)
        version.project = project
        version, saved = _contribute(request, create_version, version, request.user)
        if saved:
            return redirect("translations:version_edit", version.pk)
    return render(request, "translations/version_form.html", {"form": form, "project": project})


@login_required
@require_http_methods(["GET", "POST"])
def version_edit(request, pk):
    version = _own_version(request.user, pk)
    _step, rows = _rows(request.user, version)
    if request.method == "POST":
        changes = []
        for row in rows:
            key = f"s{row['segment'].pk}"
            if key not in request.POST:
                continue
            row["text"] = request.POST[key]
            form = TranslationTextForm({"text": request.POST[key]}, user=request.user)
            if not form.is_valid():
                row["errors"] = form.errors["text"]
            elif form.cleaned_data["text"] != row["saved"]:
                changes.append((row["segment"], form.cleaned_data["text"]))
        if not any(row["errors"] for row in rows):
            with transaction.atomic():
                for source_segment, text in changes:
                    save_translation(version, source_segment, text, request.user)
            if changes:
                messages.success(
                    request,
                    ngettext(
                        "%(count)d phrase enregistrée.",
                        "%(count)d phrases enregistrées.",
                        len(changes),
                    )
                    % {"count": len(changes)},
                )
            if request.POST.get("next") == "step":
                return redirect("translations:step_create", version.pk)
            if not changes:
                messages.info(request, _("Aucune modification."))
            return redirect("translations:version_edit", version.pk)
        messages.error(request, _("Rien n’est enregistré : corrigez les phrases signalées."))
    return render(
        request,
        "translations/version_edit.html",
        {
            "search_form": SearchForm(initial=PANEL_SEARCH_DEFAULTS),
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            **_progress(rows),
        },
    )


def _download(content, version, extension, content_type):
    response = HttpResponse(content, content_type=content_type)
    filename = export_filename(version, extension)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def version_export_text(request, pk):
    """The source text and the Latin of a version, sentence by sentence, as a text file."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version)
    content = bilingual_text(version, rows, step)
    return _download(content, version, "txt", "text/plain; charset=utf-8")


def _export_context(request, version):
    """What the TEI and TMX exports show: the rows and, for TEI, the visible evidence."""
    step, rows = _rows(request.user, version)
    for row in rows:
        for justification in row["justifications"]:
            justification.evidence_list = visible_evidences(
                request.user, justification.evidences.all(), justification=justification
            )
    now = timezone.now()
    return {
        "version": version,
        "project": version.project,
        "source": version.project.source_text,
        "step": step,
        "rows": rows,
        "exported_at": now,
        "creation_date": now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ"),
        "version_url": request.build_absolute_uri(version.get_absolute_url()),
        "site_name": _("Phraséologie latine"),
    }


def version_export_tei(request, pk):
    """The version as a TEI document: source and Latin aligned, justifications as notes."""
    version = _version(request.user, pk)
    content = render_to_string("translations/version.tei.xml", _export_context(request, version))
    return _download(content, version, "tei.xml", "application/tei+xml; charset=utf-8")


def version_export_tmx(request, pk):
    """The version as a translation memory (TMX 1.4): one unit per translated sentence."""
    version = _version(request.user, pk)
    content = render_to_string("translations/version.tmx", _export_context(request, version))
    return _download(content, version, "tmx", "application/x-tmx+xml; charset=utf-8")


def version_export_print(request, pk):
    """A printable page with the justifications as notes; the browser saves it as PDF."""
    version = _version(request.user, pk)
    step, rows = _rows(request.user, version)
    notes = []
    corpus_sources = set()
    for row in rows:
        row["notes"] = row["justifications"]
        for justification in row["notes"]:
            notes.append(justification)
            justification.note_number = len(notes)
            justification.evidence_list = visible_evidences(
                request.user, justification.evidences.all(), justification=justification
            )
            for evidence in justification.evidence_list:
                if getattr(evidence, "quotation", None):
                    edition = evidence.quotation.token.passage.edition
                    corpus_sources.add((edition.source, edition.license))
    return render(
        request,
        "translations/version_print.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "step": step,
            "rows": rows,
            "notes": notes,
            "corpus_sources": sorted(corpus_sources),
            "exported_at": timezone.now(),
        },
    )


@login_required
@require_POST
def translation_save(request, pk, segment_pk):
    """Save the Latin of one sentence from the editor; the answer is JSON."""
    version = _own_version(request.user, pk)
    source_segment = get_object_or_404(version.project.source_text.segments, pk=segment_pk)
    form = TranslationTextForm(request.POST, user=request.user)
    if not form.is_valid():
        errors = [error["message"] for error in form.errors["text"].get_json_data()]
        return JsonResponse({"errors": errors}, status=400)
    text = form.cleaned_data["text"]
    revision = save_translation(version, source_segment, text, request.user)
    return JsonResponse({"text": text, "changed": revision is not None})


@login_required
@require_http_methods(["GET", "POST"])
def version_settings(request, pk):
    version = _own_version(request.user, pk)
    form = VersionForm(request.POST or None, instance=version, user=request.user)
    if request.method == "POST" and form.is_valid():
        _saved_message(request, save_with_revision(form.save(commit=False), request.user))
        return redirect(version)
    return render(
        request,
        "translations/version_form.html",
        {"form": form, "project": version.project, "version": version},
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_publish(request, pk):
    version = _own_version(request.user, pk)
    if version.is_published:
        messages.info(request, _("Cette version est déjà publiée."))
        return redirect(version)
    # Bound on every POST: both fields are optional, so the data may be empty.
    form = PublishForm(request.POST if request.method == "POST" else None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            publish_version(
                version,
                request.user,
                message=form.cleaned_data["message"],
                show_draft_steps=form.cleaned_data["show_draft_steps"],
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("La version est publiée."))
            return redirect(version)
    return render(
        request,
        "translations/version_publish.html",
        {
            "version": version,
            "project": version.project,
            "form": form,
            "draft_step_count": version.steps.count(),
            **_progress(_rows(request.user, version)[1]),
        },
    )


# Steps


def step_list(request, pk):
    """The steps of a version the user may see, the latest first."""
    user = request.user
    version = _version(user, pk)
    steps = []
    queryset = version.steps.annotate(changed_count=Count("sentences")).order_by("-number")
    for step in queryset:
        step.version = version
        if can_view(user, step):
            steps.append(step)
    current = public_step(version)
    return render(
        request,
        "translations/step_list.html",
        {
            "version": version,
            "project": version.project,
            "steps": steps,
            "current_id": current.pk if current else None,
            "can_translate": can_translate(user, version),
        },
    )


def step_detail(request, pk, number):
    """The text of a version as a step froze it, at a fixed address that can be cited."""
    user = request.user
    version = _version(user, pk)
    step = get_object_or_404(version.steps.select_related("author"), number=number)
    step.version = version
    if not can_view(user, step):
        raise Http404
    _step, rows = _rows(user, version, step)
    visible = [
        other.number
        for other in version.steps.exclude(pk=step.pk).order_by("number")
        if can_view(user, _with_version(other, version))
    ]
    current = public_step(version)
    return render(
        request,
        "translations/step_detail.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "step": step,
            "rows": rows,
            "changed_count": step.sentences.count(),
            "previous_number": max((n for n in visible if n < step.number), default=None),
            "next_number": min((n for n in visible if n > step.number), default=None),
            "is_current": current is not None and current.pk == step.pk,
            "is_private": step.during_draft and not version.shows_draft_steps,
            "show_origin": True,
            "can_copy": can_copy(user, step),
            **_progress(rows),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def version_copy(request, pk, number):
    """Start one's own draft version from a public step of a published version."""
    source = _version(request.user, pk)
    step = get_object_or_404(source.steps, number=number)
    step.version = source
    if not can_copy(request.user, step):
        raise Http404
    form = VersionForm(
        request.POST or None,
        user=request.user,
        initial={"style": source.style, "style_note": source.style_note},
    )
    if request.method == "POST" and form.is_valid():
        version, saved = _contribute(
            request, copy_version, step, form.save(commit=False), request.user
        )
        if saved:
            messages.success(
                request, _("La copie est créée : c’est votre brouillon, visible de vous seul.")
            )
            return redirect("translations:version_edit", version.pk)
    return render(
        request,
        "translations/version_copy.html",
        {"form": form, "source": source, "step": step, "project": source.project},
    )


def step_compare(request, pk):
    """Word-by-word differences between two steps the user may see.

    By default, between the latest step and the one before it; the author may also compare
    a step with the working text.
    """
    user = request.user
    version = _version(user, pk)
    is_author = can_translate(user, version)
    steps = [
        step
        for step in version.steps.order_by("number")
        if can_view(user, _with_version(step, version))
    ]
    if not steps and not is_author:
        raise Http404
    by_number = {str(step.number): step for step in steps}
    wanted = request.GET.get("a", "")
    if wanted in by_number:
        target = by_number[wanted]
    elif (wanted == WORKING_TEXT and is_author) or not steps:
        target = None
    else:
        target = steps[-1]
    if "de" in request.GET:
        base = by_number.get(request.GET["de"])
    else:
        earlier = [step for step in steps if target is None or step.number < target.number]
        base = earlier[-1] if earlier else None

    before = _frozen_texts(base)
    if target is None:
        after = {item.segment_id: item.text for item in version.segments.all()}
    else:
        after = _frozen_texts(target)
    rows = []
    for source_segment in version.project.source_text.segments.all():
        old, new = before.get(source_segment.pk, ""), after.get(source_segment.pk, "")
        if old != new:
            rows.append(
                {
                    "segment": source_segment,
                    "before": old,
                    "after": new,
                    "chunks": word_diff(old, new),
                }
            )
    return render(
        request,
        "translations/step_compare.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "steps": steps,
            "base": base,
            "target": target,
            "is_author": is_author,
            "working": WORKING_TEXT,
            "rows": rows,
        },
    )


def _frozen_texts(step):
    if step is None:
        return {}
    return {segment_id: sentence.text for segment_id, sentence in step_sentences(step).items()}


def _with_version(step, version):
    step.version = version
    return step


@login_required
@require_http_methods(["GET", "POST"])
def step_create(request, pk):
    """What changed since the latest step, and the form to freeze it with a message."""
    version = _own_version(request.user, pk)
    form = StepForm(request.POST if request.method == "POST" else None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            step = create_step(version, request.user, form.cleaned_data["message"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("L’étape %(number)d est créée.") % {"number": step.number})
            return redirect(step)
    return render(
        request,
        "translations/step_create.html",
        {
            "version": version,
            "project": version.project,
            "form": form,
            "changes": [
                {
                    "segment": change.segment,
                    "after": change.after,
                    "chunks": word_diff(change.before, change.after),
                }
                for change in pending_changes(version)
            ],
            "waiting": waiting_justifications(version).select_related(
                "translated_segment__segment"
            ),
            "latest": latest_step(version),
        },
    )
