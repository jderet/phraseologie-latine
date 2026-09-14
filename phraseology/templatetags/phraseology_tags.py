from django import template
from django.utils.html import format_html, format_html_join

from moderation.registry import history_url

register = template.Library()


@register.filter
def history_link(obj):
    """Address of the revision history of a content."""
    return history_url(obj)


@register.simple_tag
def mark_words(tokens, marked):
    """A written sentence rebuilt from its words, the words at the ``marked`` positions marked."""
    return format_html_join(
        "",
        "{}{}{}",
        (
            (
                token.before,
                format_html("<mark>{}</mark>", token.form) if index in marked else token.form,
                token.after,
            )
            for index, token in enumerate(tokens)
        ),
    )
