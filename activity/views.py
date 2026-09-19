from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from moderation.registry import can_view

from .models import Notification
from .services import mark_read

PER_PAGE = 40


@login_required
@require_GET
def notification_list(request):
    """The user's notifications, the latest first; ``?non-lues`` shows the unread ones only."""
    notifications = Notification.objects.filter(recipient=request.user).select_related(
        "event__actor", "event__project", "event__content_type"
    )
    unread_only = "non-lues" in request.GET
    if unread_only:
        notifications = notifications.filter(read_at__isnull=True)
    page = Paginator(notifications, PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "activity/notifications.html",
        {"page": page, "unread_only": unread_only},
    )


@login_required
@require_GET
def notification_open(request, pk):
    """Mark a notification read and go to what it is about, if still visible."""
    notification = get_object_or_404(
        Notification.objects.select_related("event"), pk=pk, recipient=request.user
    )
    mark_read(request.user, [notification])
    target = notification.event.target
    if target is None or not can_view(request.user, target):
        messages.info(request, _("Ce contenu n’est plus accessible."))
        return redirect("activity:notifications")
    return redirect(target.get_absolute_url())


@login_required
@require_POST
def notifications_read(request):
    mark_read(request.user)
    messages.success(request, _("Toutes les notifications sont lues."))
    return redirect("activity:notifications")
