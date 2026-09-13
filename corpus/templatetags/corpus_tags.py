from django import template
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext

register = template.Library()


@register.filter
def format_year(year):
    """Years before the common era are stored as negative numbers."""
    if year is None:
        return ""
    if year < 0:
        return gettext("%(year)d av. J.-C.") % {"year": -year}
    return str(year)


def _word(token, highlighted):
    if token.pk in highlighted:
        return format_html('<mark id="mot-{}">{}</mark>', token.pk, token.form)
    return token.form


@register.simple_tag
def render_tokens(tokens, highlighted=()):
    """Text of a passage rebuilt from its words; highlighted words are marked."""
    return format_html_join(
        "",
        "{}{}{}",
        ((token.before, _word(token, highlighted), token.after) for token in tokens),
    )
