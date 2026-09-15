from django import template
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join

from corpus.templatetags.corpus_tags import render_sentence
from moderation.registry import history_url
from phraseology.markup import resolve
from phraseology.reading import sentence_marks

register = template.Library()


@register.inclusion_tag("phraseology/marked_form.html", takes_context=True)
def marked_form(context, unit, href="", css_class=""):
    """The reference form of a unit, the units it names highlighted, each with its bubble.

    With ``href``, the form is a link, and the bubbles follow it rather than sit inside it.
    """
    parts = []
    if unit.marked_form:
        request = context.get("request")
        user = request.user if request is not None else AnonymousUser()
        try:
            edges = unit.edges
        except ValidationError:
            edges = []
        parts = resolve(user, unit.marked_form, edges, exclude=unit)
    return {"unit": unit, "parts": parts, "href": href, "css_class": css_class}


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


@register.simple_tag(takes_context=True)
def latin_sentence(context, text, justifications=()):
    """A translated Latin sentence: known units spotted in it, words justified by an entry.

    Gives the underlined sentence (``html``) and the units spotted (``units``).
    """
    request = context.get("request")
    user = request.user if request is not None else AnonymousUser()
    words, marks, units = sentence_marks(user, text, justifications or ())
    return {"html": render_sentence(words, marks), "units": units}
