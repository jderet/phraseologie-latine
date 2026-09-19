from django import template
from django.db.models import Count

from moderation.registry import can_view

from ..services import can_star, has_starred, is_following

register = template.Library()


@register.simple_tag(takes_context=True)
def event_target(context, event):
    """{label, url} of what an event is about, or None when the reader may not see it."""
    user = context.get("user")
    target = event.target
    if target is None or user is None or not can_view(user, target):
        return None
    label_object = target
    if target._meta.label_lower == "moderation.comment":
        label_object = target.content_object
    elif target._meta.label_lower == "translations.versionmember":
        label_object = target.version
    return {"label": str(label_object), "url": target.get_absolute_url()}


@register.inclusion_tag("activity/event.html", takes_context=True)
def event_line(context, event, show_project=False):
    return {
        "event": event,
        "user": context.get("user"),
        "show_project": show_project,
    }


@register.inclusion_tag("activity/follow_button.html", takes_context=True)
def follow_button(context, obj):
    """« Suivre » or « Ne plus suivre », for a signed-in reader."""
    user = context.get("user")
    return {
        "obj": obj,
        "show": user is not None and user.is_authenticated,
        "following": user is not None and is_following(user, obj),
        "app_label": obj._meta.app_label,
        "model_name": obj._meta.model_name,
        "csrf_token": context.get("csrf_token"),
    }


@register.inclusion_tag("activity/star_button.html", takes_context=True)
def star_button(context, version):
    """The number of stars of a version, and the button to star it."""
    user = context.get("user")
    return {
        "version": version,
        "count": version.stars.count(),
        "can_star": user is not None and can_star(user, version),
        "starred": user is not None and has_starred(user, version),
        "csrf_token": context.get("csrf_token"),
    }


def star_counts(versions):
    """{version id: number of stars} for a list of versions, in one query."""
    from ..models import Star

    rows = (
        Star.objects.filter(version__in=versions)
        .values("version_id")
        .annotate(count=Count("pk"))
        .values_list("version_id", "count")
    )
    return dict(rows)
