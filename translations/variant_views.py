"""Pages of the variants of a sentence: add one, rewrite it, adopt or refuse it."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from moderation.registry import can_view

from .forms import SegmentVariantForm
from .models import Segment, SegmentVariant
from .variants import (
    add_variant,
    adopt_variant,
    can_add_variant,
    can_decide_variant,
    can_edit_variant,
    delete_variant,
    edit_variant,
    refuse_variant,
    variants_for,
)
from .views import _contribute, _version


def _variant(user, pk):
    variant = get_object_or_404(
        SegmentVariant.objects.select_related("version__project__source_text", "author", "target"),
        pk=pk,
    )
    if not can_view(user, variant.version) or not can_view(user, variant):
        raise Http404
    return variant


@login_required
@require_http_methods(["GET", "POST"])
def variant_create(request, pk, segment_pk):
    """Add a variant to one sentence: of its main text, or of another variant (« corrige »)."""
    user = request.user
    version = _version(user, pk)
    if not can_add_variant(user, version):
        raise Http404
    segment = get_object_or_404(
        Segment.objects.current(), pk=segment_pk, source_text_id=version.project.source_text_id
    )
    target = None
    asked = request.POST.get("corrige") or request.GET.get("corrige")
    if asked and asked.isdigit():
        target = _variant(user, int(asked))
        if target.version_id != version.pk or target.segment_id != segment.pk:
            raise Http404
    form = SegmentVariantForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)
        variant.version = version
        variant.segment = segment
        variant.target = target
        try:
            variant, saved = _contribute(request, add_variant, variant, user)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if saved:
                messages.success(request, _("La variante est ajoutée sous la phrase."))
                return redirect(variant.get_absolute_url())
    return render(
        request,
        "translations/variant_form.html",
        {
            "version": version,
            "project": version.project,
            "source": version.project.source_text,
            "segment": segment,
            "target": target,
            "variants": variants_for(user, version, segment),
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def variant_edit(request, pk):
    variant = _variant(request.user, pk)
    if not can_edit_variant(request.user, variant):
        raise Http404
    form = SegmentVariantForm(request.POST or None, instance=variant, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            edit_variant(variant, request.user, data["text"], data["comment"], data["status"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, _("La variante est modifiée."))
            return redirect(variant.get_absolute_url())
    return render(
        request,
        "translations/variant_form.html",
        {
            "version": variant.version,
            "project": variant.version.project,
            "source": variant.version.project.source_text,
            "segment": variant.segment,
            "target": variant.target,
            "variant": variant,
            "form": form,
        },
    )


@login_required
@require_POST
def variant_delete(request, pk):
    variant = _variant(request.user, pk)
    version = variant.version
    try:
        delete_variant(variant, request.user)
    except PermissionDenied:
        raise Http404 from None
    messages.success(request, _("La variante est retirée."))
    return redirect(version.get_absolute_url())


@login_required
@require_POST
def variant_decide(request, pk):
    """A translator adopts a proposal, which becomes the main text, or refuses it."""
    variant = _variant(request.user, pk)
    decision = request.POST.get("decision")
    if decision not in ("adopt", "refuse"):
        return HttpResponseBadRequest()
    if not can_decide_variant(request.user, variant):
        raise Http404
    try:
        if decision == "adopt":
            adopt_variant(variant, request.user)
            messages.success(request, _("La variante devient le texte principal de la phrase."))
        else:
            refuse_variant(variant, request.user)
            messages.success(request, _("La variante est refusée : elle reste pour référence."))
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect(variant.get_absolute_url())
