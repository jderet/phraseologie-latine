"""Phraseology in the text being read: the attestations of a page, as the reader filters them.

Each occurrence is underlined word by word, in the colour of the type of its unit and with the
line of its status, so that an automatic attestation is never shown as validated (rule 4).
Occurrences that share words are drawn on different tracks, one line under the other. In a
Latin sentence being translated, known units are only spotted, as suggestions, and the words
a justification cites an entry for are marked apart.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from corpus.models import Work
from moderation.registry import can_view

from .models import Attestation, Kind, UsageMark
from .spotting import spot_units, visible_units, word_offsets

VALIDATED, PROPOSED, AUTOMATIC = "validated", "proposed", "automatic"
STATUS_LABELS = {
    VALIDATED: _("validées"),
    PROPOSED: _("proposées"),
    AUTOMATIC: _("repérées automatiquement"),
}
DEFAULT_STATUSES = (VALIDATED, PROPOSED)
# How a unit is marked in a translated sentence: spotted there, or cited by a justification.
SPOTTED, JUSTIFIED = "spotted", "justified"
# Lines drawn under a word at most; further occurrences share the last one.
MAX_TRACKS = 4
SESSION_KEY = "reading_filters"


def shown_status(attestation):
    """How an attestation is shown: validated, proposed by people, or found automatically."""
    if attestation.status == Attestation.Status.VALIDATED:
        return VALIDATED
    if attestation.level == Attestation.Level.AUTOMATIC:
        return AUTOMATIC
    return PROPOSED


def status_condition(statuses):
    """Attestations shown with one of these statuses; rejected ones never are."""
    conditions = {
        VALIDATED: Q(status=Attestation.Status.VALIDATED),
        PROPOSED: Q(status=Attestation.Status.PROPOSED, level=Attestation.Level.VALIDATED),
        AUTOMATIC: Q(status=Attestation.Status.PROPOSED, level=Attestation.Level.AUTOMATIC),
    }
    condition = Q(pk__in=[])
    for status in statuses:
        condition |= conditions[status]
    return condition


@dataclass(frozen=True)
class ReadingFilters:
    """What the reader underlines; no type, mark or register chosen means all of them."""

    statuses: tuple = DEFAULT_STATUSES
    kinds: tuple = ()
    marks: tuple = ()
    registers: tuple = ()

    @property
    def is_default(self):
        return self == ReadingFilters()


def _chosen(values, allowed):
    return tuple(value for value in dict.fromkeys(values) if value in allowed)


def _filters(statuses, kinds, marks, registers):
    return ReadingFilters(
        _chosen(statuses, STATUS_LABELS),
        _chosen(kinds, Kind.values),
        _chosen(marks, UsageMark.values),
        _chosen(registers, Work.Register.values),
    )


def reading_filters(request):
    """The reader's filters: sent by the form, else remembered for the session, else default."""
    asked = request.GET.get("filtres")
    if asked == "defaut":
        request.session.pop(SESSION_KEY, None)
        return ReadingFilters()
    if asked == "1":
        values = request.GET.getlist
        filters = _filters(values("statut"), values("type"), values("marque"), values("registre"))
        if filters.is_default:
            request.session.pop(SESSION_KEY, None)
        else:
            request.session[SESSION_KEY] = [
                list(filters.statuses),
                list(filters.kinds),
                list(filters.marks),
                list(filters.registers),
            ]
        return filters
    saved = request.session.get(SESSION_KEY)
    if isinstance(saved, list) and len(saved) == 4:
        return _filters(*saved)
    return ReadingFilters()


def focused_unit(user, value):
    """The unit the reader follows alone, if the user may see it."""
    value = str(value or "")
    return visible_units(user).filter(pk=int(value)).first() if value.isdigit() else None


def visible_attestations(user, filters=None, unit=None):
    """Attestations the user may see, as filtered."""
    filters = filters or ReadingFilters()
    attestations = (
        Attestation.objects.active()
        .filter(status_condition(filters.statuses), is_hidden=False, unit__in=visible_units(user))
        .select_related("unit")
    )
    if filters.kinds:
        attestations = attestations.filter(unit__kind__in=filters.kinds)
    if filters.registers:
        attestations = attestations.filter(unit__register__in=filters.registers)
    if filters.marks:
        condition = Q(pk__in=[])
        for mark in filters.marks:
            condition |= Q(unit__usage_marks__contains=[mark])
        attestations = attestations.filter(condition)
    if unit is not None:
        attestations = attestations.filter(unit=unit)
    return attestations


def page_attestations(user, passages, filters=None, unit=None):
    """Attestations beginning in these passages that the user may see, as filtered."""
    return visible_attestations(user, filters, unit).filter(passage__in=passages)


@dataclass
class Occurrence:
    """An attestation drawn on a page: its words there, in textual order, and its track."""

    attestation: Attestation
    reference: str
    words: list
    start: int
    end: int
    track: int = 0
    edition: int = 0

    @property
    def key(self):
        return self.attestation.pk

    @property
    def unit(self):
        return self.attestation.unit

    @property
    def status(self):
        return shown_status(self.attestation)

    @property
    def css(self):
        return f"u k-{self.unit.kind or 'none'} s-{self.status} t{self.track}"


def assign_tracks(marks):
    """Give each mark the first track free over its span, from the start of the text."""
    ends = []
    for mark in sorted(marks, key=lambda item: (item.start, -item.end)):
        track = next((index for index, end in enumerate(ends) if end < mark.start), None)
        if track is None:
            track = len(ends)
            ends.append(mark.end)
        else:
            ends[track] = mark.end
        mark.track = min(track, MAX_TRACKS - 1)


def page_occurrences(attestations, token_ids, references=None):
    """The occurrences drawn among some words: the words of each attestation found there.

    ``references`` maps passages to their reference. Tracks are counted edition by edition,
    since positions are.
    """
    references = references or {}
    attestations = {attestation.pk: attestation for attestation in attestations}
    rows = (
        Attestation.tokens.through.objects.filter(attestation_id__in=list(attestations))
        .order_by("token__position")
        .values_list("attestation_id", "token_id", "token__position", "token__edition_id")
    )
    found, editions = defaultdict(list), {}
    for attestation_id, token_id, position, edition_id in rows:
        if token_id in token_ids:
            found[attestation_id].append((position, token_id))
            editions[attestation_id] = edition_id
    occurrences = [
        Occurrence(
            attestations[pk],
            references.get(attestations[pk].passage_id, ""),
            [token_id for _position, token_id in words],
            words[0][0],
            words[-1][0],
            edition=editions[pk],
        )
        for pk, words in found.items()
    ]
    by_edition = defaultdict(list)
    for occurrence in occurrences:
        by_edition[occurrence.edition].append(occurrence)
    for group in by_edition.values():
        assign_tracks(group)
    return sorted(occurrences, key=lambda item: (item.edition, item.start, item.track))


def word_occurrences(user, token_ids, filters=None):
    """The occurrences among some words of the corpus, such as the quotations of a search."""
    token_ids = set(token_ids)
    if not token_ids:
        return []
    covering = Attestation.tokens.through.objects.filter(token_id__in=token_ids)
    attestations = visible_attestations(user, filters).filter(
        pk__in=covering.values("attestation_id")
    )
    return page_occurrences(attestations, token_ids)


def word_marks(occurrences):
    """The occurrences underlining each word."""
    marks = defaultdict(list)
    for occurrence in occurrences:
        for token_id in occurrence.words:
            marks[token_id].append(occurrence)
    return marks


def units_on_page(occurrences):
    """The units underlined on a page, in the order they first occur, with their occurrences."""
    units = {}
    for occurrence in occurrences:
        entry = units.setdefault(occurrence.unit.pk, {"unit": occurrence.unit, "occurrences": []})
        entry["occurrences"].append(occurrence)
    return list(units.values())


def legend_kinds(occurrences):
    """The types of the units underlined on a page, as (value, label)."""
    present = {occurrence.unit.kind for occurrence in occurrences}
    kinds = [(value, label) for value, label in Kind.choices if value in present]
    if "" in present:
        kinds.append(("none", _("sans type")))
    return kinds


def unit_neighbours(unit, edition, page, filters):
    """The occurrences of a unit in an edition just before and after a page, and their number."""
    attestations = (
        Attestation.objects.active()
        .filter(
            status_condition(filters.statuses),
            unit=unit,
            is_hidden=False,
            passage__edition=edition,
        )
        .select_related("passage")
    )
    return {
        "previous": attestations.filter(passage__order__lt=page.start)
        .order_by("-passage__order", "-pk")
        .first(),
        "following": attestations.filter(passage__order__gt=page.end)
        .order_by("passage__order", "pk")
        .first(),
        "total": attestations.count(),
    }


@dataclass
class TextMark:
    """A unit marked in a Latin sentence being translated, over some of its words."""

    key: str
    unit: object
    status: str
    positions: list
    track: int = 0

    @property
    def start(self):
        return self.positions[0]

    @property
    def end(self):
        return self.positions[-1]

    @property
    def css(self):
        return f"u k-{self.unit.kind or 'none'} s-{self.status} t{self.track}"

    @property
    def title(self):
        return self.unit.reference_form


def sentence_marks(user, text, justifications=()):
    """A Latin sentence being translated: its words, their marks by position, the units spotted.

    Known units are spotted as suggestions (Q47); the words of a justification that still
    matches the sentence are marked with the entries it cites, as the user may see them.
    """
    words, spots = spot_units(text, user, describe=False)
    marks = [
        TextMark(f"s{spot.unit.pk}", spot.unit, SPOTTED, list(spot.positions)) for spot in spots
    ]
    offsets = word_offsets(words)
    for justification in justifications:
        location = justification.locate()
        if location is None:
            continue
        start, end = location
        positions = [
            index for index, (first, last) in enumerate(offsets) if first < end and last > start
        ]
        if not positions:
            continue
        for unit in justification.units.all():
            if can_view(user, unit):
                key = f"j{justification.pk}-{unit.pk}"
                marks.append(TextMark(key, unit, JUSTIFIED, positions))
    assign_tracks(marks)
    by_position = defaultdict(list)
    for mark in marks:
        for position in mark.positions:
            by_position[position].append(mark)
    return words, by_position, [spot.unit for spot in spots]
