"""Showing evidence and justified words, on justification pages and in exports."""

from django.db.models import Prefetch

from corpus.models import Token
from corpus.search import quotation
from moderation.registry import can_view

from .models import Evidence


def visible_evidences(user, queryset, **parent):
    """Evidence that is not withdrawn and that the user may see, with its corpus quotation.

    ``parent`` gives the justification or the challenge already loaded, to spare queries.
    """
    tokens = Token.objects.select_related("passage__edition__work__author")
    evidences = []
    queryset = (
        queryset.filter(is_withdrawn=False)
        .select_related("work")
        .prefetch_related(Prefetch("tokens", queryset=tokens))
    )
    for evidence in queryset:
        for name, value in parent.items():
            setattr(evidence, name, value)
        if not can_view(user, evidence):
            continue
        cited = list(evidence.tokens.all())
        if evidence.kind == Evidence.Kind.CORPUS and cited:
            evidence.quotation = quotation(cited)
        evidences.append(evidence)
    return evidences


def excerpt_parts(obj):
    """The Latin sentence cut around the words of a justification or a challenge."""
    span = obj.locate()
    text = obj.translated_segment.text
    return (text[: span[0]], text[span[0] : span[1]], text[span[1] :]) if span else None
