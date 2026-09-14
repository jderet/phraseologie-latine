from django import template

from moderation.registry import history_url

register = template.Library()


@register.filter
def history_link(obj):
    """Address of the revision history of a content."""
    return history_url(obj)
