from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from moderation.registry import can_view, find_registration
from translations.members import pending_invitations
from translations.models import SegmentVariant, TranslationVersion

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


@login_required
@require_GET
def workshop(request):
    """The user's desk: invitations, variants to decide, versions, news."""
    user = request.user
    versions = list(
        TranslationVersion.objects.written_by(user)
        .filter(is_hidden=False)
        .select_related("project__source_text", "author")
        .order_by("-created_at")
    )
    for version in versions:
        total = version.project.source_text.segments.current().count()
        done = version.segments.current().exclude(text="").count()
        version.progress = {"done": done, "total": total, "percent": done * 100 // (total or 1)}
    waiting = (
        SegmentVariant.objects.filter(
            version__in=versions,
            status=SegmentVariant.Status.PROPOSAL,
            decision=SegmentVariant.Decision.PENDING,
            is_hidden=False,
        )
        .select_related("author", "version__project")
        .order_by("created_at")[:20]
    )
    mine = (
        SegmentVariant.objects.filter(
            author=user,
            status=SegmentVariant.Status.PROPOSAL,
            decision=SegmentVariant.Decision.PENDING,
            is_hidden=False,
        )
        .select_related("version__project")
        .order_by("created_at")[:20]
    )
    notifications = Notification.objects.filter(recipient=user).select_related(
        "event__actor", "event__project", "event__content_type"
    )[:8]
    return render(
        request,
        "activity/workshop.html",
        {
            "invitations": pending_invitations(user),
            "waiting": waiting,
            "mine": mine,
            "drafts": [version for version in versions if version.is_draft],
            "published": [version for version in versions if version.is_published],
            "notifications": notifications,
        },
    )
