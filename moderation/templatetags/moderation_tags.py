from django import template

from ..registry import history_url, report_url

register = template.Library()


@register.inclusion_tag("moderation/links.html", takes_context=True)
def moderation_links(context, obj):
    """Links to the history of a content and to the report form."""
    return {
        "history_url": history_url(obj),
        "report_url": report_url(obj),
        "user": context.get("user"),
    }
