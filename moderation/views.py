from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from accounts.limits import ContributionLimitReached
from accounts.roles import is_reviewer

from .forms import ReportForm, ResolveReportForm
from .models import Report, Revision
from .registry import can_revert, can_view, find_registration, history_url
from .services import create_report, resolve_report, revert_to

HISTORY_LENGTH = 200


def _visible_object(user, app_label, model_name, pk):
    registration = find_registration(app_label, model_name)
    if registration is None:
        raise Http404
    obj = get_object_or_404(registration.model._base_manager, pk=pk)
    if not can_view(user, obj):
        raise Http404
    return obj


def _object_url(obj):
    get_url = getattr(obj, "get_absolute_url", None)
    return get_url() if get_url else history_url(obj)


def history(request, app_label, model_name, pk):
    obj = _visible_object(request.user, app_label, model_name, pk)
    revisions = Revision.objects.for_object(obj).select_related("author", "content_type")
    return render(
        request,
        "moderation/history.html",
        {
            "object": obj,
            "revisions": revisions[:HISTORY_LENGTH],
            "can_revert": can_revert(request.user, obj),
        },
    )


@login_required
@require_POST
def revert(request, pk):
    revision = get_object_or_404(Revision.objects.select_related("content_type"), pk=pk)
    obj = revision.content_object
    if obj is None:
        raise Http404
    _visible_object(request.user, obj._meta.app_label, obj._meta.model_name, obj.pk)
    try:
        result = revert_to(revision, request.user)
    except ContributionLimitReached as error:
        messages.error(request, str(error))
    else:
        if result is None:
            messages.info(request, _("Le contenu est déjà dans cet état."))
        else:
            messages.success(request, _("La version choisie est rétablie."))
    return redirect(history_url(obj))


@login_required
@require_http_methods(["GET", "POST"])
def report(request, app_label, model_name, pk):
    obj = _visible_object(request.user, app_label, model_name, pk)
    if request.method == "POST":
        form = ReportForm(request.POST)
        if form.is_valid():
            _report, created = create_report(
                request.user, obj, form.cleaned_data["reason"], form.cleaned_data["message"]
            )
            if created:
                messages.success(
                    request, _("Merci : votre signalement sera examiné par l’équipe de relecture.")
                )
            else:
                messages.info(
                    request, _("Vous avez déjà signalé ce contenu ; il est en cours d’examen.")
                )
            return redirect(_object_url(obj))
    else:
        form = ReportForm()
    return render(request, "moderation/report.html", {"object": obj, "form": form})


@login_required
def report_queue(request):
    if not is_reviewer(request.user):
        raise PermissionDenied
    reports = (
        Report.objects.filter(status=Report.Status.OPEN)
        .select_related("author", "content_type")
        .order_by("created_at")
    )
    items = [
        {"report": item, "form": ResolveReportForm(auto_id=f"report-{item.pk}-%s")}
        for item in reports
    ]
    return render(request, "moderation/report_queue.html", {"items": items})


@login_required
@require_POST
def handle_report(request, pk):
    if not is_reviewer(request.user):
        raise PermissionDenied
    item = get_object_or_404(Report, pk=pk, status=Report.Status.OPEN)
    form = ResolveReportForm(request.POST)
    if form.is_valid():
        decision = form.cleaned_data["decision"]
        status = (
            Report.Status.REJECTED
            if decision == ResolveReportForm.REJECTED
            else Report.Status.HANDLED
        )
        resolve_report(
            item,
            request.user,
            status,
            form.cleaned_data["resolution"],
            hide=decision == ResolveReportForm.HIDE,
        )
        messages.success(request, _("Signalement traité."))
    else:
        messages.error(request, _("Choisissez une décision."))
    return redirect("moderation:report_queue")
