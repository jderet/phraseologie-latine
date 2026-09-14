"""Known units in a Latin sentence being written, with their attestations (Q47).

The server does not lemmatize. The forms of each lemma of a unit are taken once from the
analysed corpus and stored with the unit (``UnitForm``); a sentence is then compared word by
word. A unit without schema is recognized by the words of its reference form. Words are only
found near each other: their syntactic relation is not checked, so a spot is a suggestion.
"""

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product

from django.db.models import Prefetch, Q

from corpus.models import Token
from corpus.search import default_layer, quotation
from corpus.text import normalize, tokenize

from .models import Attestation, Unit, UnitForm
from .schema import schema_lemmas

# The words of a unit may lie this many words apart, for each word beyond the first.
SPAN_PER_WORD = 5
MAX_SPOTS = 10
ATTESTATIONS_SHOWN = 3
# Positions tried for each lemma, in a sentence where it occurs many times.
MAX_CHOICES = 12
STATUS_ORDER = {
    Unit.Status.VALIDATED: 0,
    Unit.Status.PROPOSED: 1,
    Unit.Status.CONTESTED: 2,
    Unit.Status.DRAFT: 3,
}


def lemma_forms(lemma, layer):
    """Normalized forms the analysed corpus gives to a lemma, the lemma itself included."""
    norms = (
        Token.objects.filter(
            edition__is_current=True, analyses__layer=layer, analyses__lemma_norm=lemma
        )
        .values_list("norm", flat=True)
        .distinct()
    )
    # Abbreviations (P.) and Greek in Beta code (adi/re) would spot units everywhere.
    return {norm for norm in norms if norm.isalpha() and len(norm) > 1} | {lemma}


def refresh_unit_forms(unit):
    """Store the forms that recognize a unit: of its lemmas, or of its reference form."""
    UnitForm.objects.filter(unit=unit).delete()
    layer = default_layer()
    rows = []
    if unit.schema and layer is not None:
        for lemma in schema_lemmas(unit.edges):
            norms = lemma_forms(lemma, layer)
            rows += [UnitForm(unit=unit, lemma=lemma, norm=norm) for norm in sorted(norms)]
    else:
        words = dict.fromkeys(normalize(token.form) for token in tokenize(unit.reference_form))
        rows = [UnitForm(unit=unit, lemma=f"={word}", norm=word) for word in words]
    UnitForm.objects.bulk_create(rows)
    return len(rows)


@dataclass
class Spot:
    unit: Unit
    positions: list
    words: list
    # The words of the sentence from the first word of the unit to its last, and their start.
    excerpt: str = ""
    start: int = 0
    sense: object = None
    attestations: list = field(default_factory=list)


def visible_units(user):
    """Public units, and the user's own drafts (rule 8)."""
    condition = Q(is_hidden=False) & ~Q(status=Unit.Status.DRAFT)
    if user.is_authenticated:
        condition |= Q(is_hidden=False, status=Unit.Status.DRAFT, created_by=user)
    return Unit.objects.filter(condition)


def closest_positions(choices):
    """One position for each lemma, all different and as close as possible: (span, positions)."""
    best = None
    for combination in product(*(positions[:MAX_CHOICES] for positions in choices)):
        if len(set(combination)) < len(combination):
            continue
        span = max(combination) - min(combination)
        if best is None or span < best[0]:
            best = (span, sorted(combination))
    return best


def unit_attestations(unit, limit=ATTESTATIONS_SHOWN):
    """Attestations of a unit with their quotation, examples and validated ones first."""
    tokens = Token.objects.select_related("passage__edition__work__author")
    attestations = (
        unit.attestations.active()
        .filter(is_hidden=False)
        .exclude(status=Attestation.Status.REJECTED)
        .prefetch_related(Prefetch("tokens", queryset=tokens))
    )
    chosen = sorted(
        attestations,
        key=lambda item: (
            not item.is_example,
            item.status != Attestation.Status.VALIDATED,
            item.pk,
        ),
    )[:limit]
    for attestation in chosen:
        attestation.quotation = quotation(list(attestation.tokens.all()))
    return chosen


def word_offsets(tokens):
    """(start, end) of each word in the text the tokens were cut from."""
    offsets, position = [], 0
    for token in tokens:
        start = position + len(token.before)
        offsets.append((start, start + len(token.form)))
        position = start + len(token.form) + len(token.after)
    return offsets


def spot_units(text, user, describe=True):
    """The words of a sentence, and the known units found in it, validated units first.

    With ``describe``, each spot also has the first sense and a few attestations of its unit.
    """
    text = unicodedata.normalize("NFC", text or "")
    tokens = tokenize(text)
    words = [normalize(token.form) for token in tokens]
    if not words:
        return tokens, []
    rows = UnitForm.objects.filter(norm__in=set(words), unit__in=visible_units(user))
    found = defaultdict(lambda: defaultdict(set))
    for unit_id, lemma, norm in rows.values_list("unit_id", "lemma", "norm"):
        found[unit_id][lemma].add(norm)
    needed = defaultdict(set)
    lemmas = UnitForm.objects.filter(unit_id__in=list(found)).values_list("unit_id", "lemma")
    for unit_id, lemma in lemmas.distinct():
        needed[unit_id].add(lemma)
    matches = {}
    for unit_id, norms in found.items():
        if set(norms) != needed[unit_id]:
            continue
        choices = [
            [index for index, word in enumerate(words) if word in norms[lemma]]
            for lemma in sorted(norms)
        ]
        best = closest_positions(choices)
        if best is not None and best[0] <= SPAN_PER_WORD * (len(choices) - 1):
            matches[unit_id] = best[1]
    units = Unit.objects.in_bulk(list(matches))
    offsets = word_offsets(tokens)
    spots = []
    for pk, positions in matches.items():
        start, end = offsets[positions[0]][0], offsets[positions[-1]][1]
        words_found = [tokens[index].form for index in positions]
        spots.append(Spot(units[pk], positions, words_found, text[start:end], start))
    spots.sort(
        key=lambda spot: (
            STATUS_ORDER.get(spot.unit.status, len(STATUS_ORDER)),
            spot.positions[0],
            spot.unit.reference_form,
        )
    )
    spots = spots[:MAX_SPOTS]
    if describe:
        for spot in spots:
            spot.sense = spot.unit.senses.active().filter(is_hidden=False).first()
            spot.attestations = unit_attestations(spot.unit)
    return tokens, spots
