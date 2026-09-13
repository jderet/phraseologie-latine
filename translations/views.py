from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods

from accounts.limits import ContributionLimitReached
from moderation.registry import can_view
from moderation.services import save_with_revision

from .forms import (
    ProjectForm,
    SourceTextEditForm,
    SourceTextForm,
    TranslationTextForm,
    VersionForm,
)
from .models import SourceText, TranslationProject, TranslationVersion
from .permissions import can_edit, can_translate
from .segmentation import from_lines, segment, to_lines
from .services import (
    create_project,
    create_source_text,
    create_version,
    publish_version,
    save_translation,
)

ITEMS_PER_PAGE = 50


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
    versions = (
        project.versions.visible_to(request.user)
        .select_related("author")
        .annotate(translated_count=Count("segments", filter=~Q(segments__text="")))
    )
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


# Versions


def _version(user, pk):
    queryset = TranslationVersion.objects.select_related("project__source_text", "author")
    return _visible(user, queryset, pk)


def _own_version(user, pk):
    version = _version(user, pk)
    if not can_translate(user, version):
        raise PermissionDenied
    return version


def _rows(user, version):
    """Each sentence of the source text with its Latin in the version."""
    translated = {item.segment_id: item for item in version.segments.all()}
    rows = []
    for source_segment in version.project.source_text.segments.all():
        item = translated.get(source_segment.pk)
        text = item.text if item else ""
        rows.append(
            {
                "segment": source_segment,
                "translation": item,
                "saved": text,
                "text": text,
                "hidden": item is not None and not can_view(user, item),
                "errors": None,
            }
        )
    return rows


def _progress(rows):
    return {
        "translated_count": sum(1 for row in rows if row["saved"]),
        "segment_count": len(rows),
    }


def version_detail(request, pk):
    version = _version(request.user, pk)
    rows = _rows(request.user, version)
    return render(
        request,
        "translations/version_detail.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            "can_translate": can_translate(request.user, version),
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
    rows = _rows(request.user, version)
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
            else:
                messages.info(request, _("Aucune modification."))
            return redirect("translations:version_edit", version.pk)
        messages.error(request, _("Rien n’est enregistré : corrigez les phrases signalées."))
    return render(
        request,
        "translations/version_edit.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "rows": rows,
            **_progress(rows),
        },
    )


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
    if request.method == "POST":
        try:
            publish_version(version, request.user)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("La version est publiée."))
            return redirect(version)
    return render(
        request,
        "translations/version_publish.html",
        {"version": version, "project": version.project, **_progress(_rows(request.user, version))},
    )
