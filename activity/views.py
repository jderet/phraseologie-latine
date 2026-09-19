from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from moderation.registry import can_view, find_registration
from translations.models import TranslationVersion

from .models import Notification
from .services import (
    FOLLOWABLE,
    follow,
    has_starred,
    is_following,
    mark_read,
    star,
    unfollow,
    unstar,
)

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


@login_required
@require_POST
def follow_toggle(request, app_label, model_name, pk):
    """Follow a content, or stop following it."""
    label = f"{app_label}.{model_name}"
    registration = find_registration(app_label, model_name)
    if label not in FOLLOWABLE or registration is None:
        raise Http404
    obj = get_object_or_404(registration.model._base_manager, pk=pk)
    if not can_view(request.user, obj):
        raise Http404
    if is_following(request.user, obj):
        unfollow(request.user, obj)
        messages.success(request, _("Vous ne suivez plus ce contenu."))
    else:
        follow(request.user, obj)
        messages.success(
            request, _("Vous suivez ce contenu : ce qui lui arrive entre dans vos notifications.")
        )
    return redirect(obj.get_absolute_url())


@login_required
@require_POST
def star_toggle(request, pk):
    """Star a published version, or take the star back."""
    version = get_object_or_404(TranslationVersion, pk=pk)
    if not can_view(request.user, version):
        raise Http404
    if has_starred(request.user, version):
        unstar(request.user, version)
    elif star(request.user, version) is None:
        messages.error(request, _("Seule une version publiée reçoit des étoiles."))
    return redirect(version.get_absolute_url())
