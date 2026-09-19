"""Occurrences of known schemas not yet attested, suggested to annotators in the text they read.

They come from the automatic analysis and are not recorded until someone confirms one: in the
core it becomes a proposed attestation, which a reviewer checks; outside the core it is recorded
as found automatically, and never validated (T2).
"""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from corpus.models import Token, TokenAnalysis
from justifications.services import corpus_evidence

from .frequency import occurrence_words, schema_matches
from .models import Attestation, Unit
from .permissions import can_edit_unit
from .schema import parse_schema, required_edges, schema_lemmas
from .services import add_attestations, record_automatic_attestations
from .spotting import visible_units


@dataclass
class Suggestion:
    """An occurrence of the schema of a unit on a page, with no attestation of the unit there."""

    unit: Unit
    words: tuple
    start: int = 0
    end: int = 0
    track: int = 0
    edition: int = 0

    @property
    def key(self):
        """The unit and the words, which the reading script reads back."""
        return "_".join(["s", str(self.unit.pk), *(str(pk) for pk in self.words)])

    @property
    def css(self):
        return f"u k-{self.unit.kind or 'none'} s-suggested t{self.track}"


def _attested(unit, token_ids):
    """The word sets of the attestations of a unit among some words, rejected ones included."""
    rows = Attestation.tokens.through.objects.filter(
        attestation__unit=unit, attestation__is_withdrawn=False, token_id__in=token_ids
    ).values_list("attestation_id", "token_id")
    words = defaultdict(set)
    for attestation_id, token_id in rows:
        words[attestation_id].add(token_id)
    return list(words.values())


def page_suggestions(user, passages, token_ids, layer):
    """The occurrences, among the words of a page, of the units the user may complete.

    Only units whose lemmas all occur on the page are tried; an occurrence already covered by
    an attestation of the unit, even a rejected one, is left out, as in a survey.
    """
    if layer is None or not passages:
        return []
    lemmas = set(
        TokenAnalysis.objects.filter(layer=layer, token__passage__in=passages)
        .values_list("lemma_norm", flat=True)
        .distinct()
    )
    suggestions = []
    for unit in visible_units(user).exclude(schema="").order_by("reference_form", "pk"):
        try:
            edges = parse_schema(unit.schema)
        except ValidationError:
            continue
        needed = set(schema_lemmas(required_edges(edges)))
        if not needed <= lemmas or not can_edit_unit(user, unit):
            continue
        roots = list(
            schema_matches(edges, layer)
            .filter(token__passage__in=passages)
            .values_list("token_id", "part", "token__position")
        )
        if not roots:
            continue
        attested = _attested(unit, token_ids)
        for words in occurrence_words(roots, edges, layer):
            chosen = set(words)
            if chosen <= token_ids and not any(chosen <= covered for covered in attested):
                suggestions.append(Suggestion(unit, words))
    places = {
        pk: (position, edition_id)
        for pk, position, edition_id in Token.objects.filter(
            pk__in={pk for suggestion in suggestions for pk in suggestion.words}
        ).values_list("pk", "position", "edition_id")
    }
    for suggestion in suggestions:
        suggestion.start = places[suggestion.words[0]][0]
        suggestion.end = places[suggestion.words[-1]][0]
        suggestion.edition = places[suggestion.words[0]][1]
    return suggestions


def confirm_suggestion(unit, words, user):
    """Record a suggested occurrence: proposed in the core, found automatically outside it.

    Returns the attestations created: none when these words already attest the unit.
    """
    evidence = corpus_evidence(words)
    ids = tuple(token.pk for token in evidence.tokens)
    if any(set(ids) == covered for covered in _attested(unit, ids)):
        return []
    if evidence.tokens[0].passage.edition.work.is_core:
        return add_attestations(unit, [evidence], user, origin=Attestation.Origin.QUERY)
    return record_automatic_attestations(unit, [ids], user)
