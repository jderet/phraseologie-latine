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


def _between(previous, token):
    """A space where a quotation goes on into the next passage, which the text lacks there."""
    if previous is None or previous.passage_id == token.passage_id:
        return ""
    return "" if previous.after[-1:].isspace() else " "


def _target(token, marks, highlighted, targets):
    """A word inside the lines of the occurrences it belongs to; for the reader, a target."""
    html = _word(token, highlighted)
    if targets:
        html = format_html('<span data-t="{}">{}</span>', token.pk, html)
    for mark in sorted(marks.get(token.pk, ()), key=lambda item: item.track):
        html = format_html('<span class="{}" data-o="{}">{}</span>', mark.css, mark.key, html)
    return html


@register.simple_tag
def render_words(tokens, marks=None, highlighted=(), targets=True):
    """Text of corpus words with their phraseology underlined.

    ``marks`` maps word identifiers to objects with ``css``, ``key`` and ``track``; the first
    track is drawn closest to the word. With ``targets``, each word can be pointed at by the
    reading script. Highlighted words are marked as by ``render_tokens``.
    """
    tokens = list(tokens)
    marks = marks or {}
    highlighted = highlighted or ()
    return format_html_join(
        "",
        "{}{}{}{}",
        (
            (
                _between(previous, token),
                token.before,
                _target(token, marks, highlighted, targets),
                token.after,
            )
            for previous, token in zip([None, *tokens], tokens, strict=False)
        ),
    )


@register.simple_tag
def render_sentence(words, marks=None):
    """A Latin sentence being written: ``marks`` maps the positions of its words to units."""
    marks = marks or {}

    def word(index, token):
        html = token.form
        for mark in sorted(marks.get(index, ()), key=lambda item: item.track):
            html = format_html('<span class="{}" title="{}">{}</span>', mark.css, mark.title, html)
        return html

    return format_html_join(
        "",
        "{}{}{}",
        ((token.before, word(index, token), token.after) for index, token in enumerate(words)),
    )


@register.simple_tag
def render_tokens(tokens, highlighted=()):
    """Text of a passage rebuilt from its words; highlighted words are marked."""
    tokens = list(tokens)
    return format_html_join(
        "",
        "{}{}{}{}",
        (
            (_between(previous, token), token.before, _word(token, highlighted), token.after)
            for previous, token in zip([None, *tokens], tokens, strict=False)
        ),
    )
