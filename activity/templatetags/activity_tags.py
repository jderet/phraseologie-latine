from django import template

from moderation.registry import can_view

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
