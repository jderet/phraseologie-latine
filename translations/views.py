from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from accounts.limits import ContributionLimitReached
from moderation.registry import can_view
from moderation.services import save_with_revision

from .forms import SourceTextEditForm, SourceTextForm
from .models import SourceText
from .permissions import can_edit
from .segmentation import from_lines, segment, to_lines
from .services import create_source_text

TEXTS_PER_PAGE = 50


def _visible(user, queryset, pk):
    obj = get_object_or_404(queryset, pk=pk)
    if not can_view(user, obj):
        raise Http404
    return obj


def source_list(request):
    texts = (
        SourceText.objects.filter(is_hidden=False)
        .select_related("added_by")
        .annotate(segment_count=Count("segments"))
        .order_by("-created_at", "-pk")
    )
    page = Paginator(texts, TEXTS_PER_PAGE).get_page(request.GET.get("page"))
    return render(request, "translations/source_list.html", {"page": page})


def source_detail(request, pk):
    source = _visible(request.user, SourceText.objects.select_related("added_by"), pk)
    return render(
        request,
        "translations/source_detail.html",
        {
            "source": source,
            "segments": source.segments.all(),
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
        try:
            source = create_source_text(form.save(commit=False), request.user, form.sentences)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        else:
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
        try:
            revision = save_with_revision(form.save(commit=False), request.user)
        except ContributionLimitReached as error:
            messages.error(request, str(error))
        else:
            if revision is None:
                messages.info(request, _("Aucune modification."))
            else:
                messages.success(request, _("Les modifications sont enregistrées."))
            return redirect(source)
    return render(request, "translations/source_edit.html", {"form": form, "source": source})
