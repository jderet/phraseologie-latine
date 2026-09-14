from django import template
from django.contrib.auth.models import AnonymousUser
from django.utils.html import format_html, format_html_join

from corpus.templatetags.corpus_tags import render_sentence
from moderation.registry import history_url
from phraseology.reading import sentence_marks

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


@register.simple_tag(takes_context=True)
def latin_sentence(context, text, justifications=()):
    """A translated Latin sentence: known units spotted in it, words justified by an entry.

    Gives the underlined sentence (``html``) and the units spotted (``units``).
    """
    request = context.get("request")
    user = request.user if request is not None else AnonymousUser()
    words, marks, units = sentence_marks(user, text, justifications or ())
    return {"html": render_sentence(words, marks), "units": units}
