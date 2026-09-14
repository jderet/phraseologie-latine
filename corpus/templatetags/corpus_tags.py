from django import template
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext

from corpus.models import Work

register = template.Library()


@register.simple_tag
def poetry_mark(hit):
    """A quotation in verse is marked as such: poetry is no norm for prose (Q21)."""
    if hit.token.passage.edition.work.form != Work.Form.VERSE:
        return ""
    return format_html(
        '<span class="badge poetry-mark" title="{}">{}</span>',
        gettext("Poésie : ne fait pas norme pour la prose"),
        gettext("poésie"),
    )


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
