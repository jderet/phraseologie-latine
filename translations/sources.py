"""The sentences of a source text through its changes, and how the Latin follows them.

A change never edits a sentence in place: it removes sentences and adds new ones. The state of
a text is the number of its latest change, 0 as it was added; a step freezes the state it saw
(``VersionStep.source_state``). No change removes a sentence without adding one: the first
sentence it adds carries the Latin of those it removes.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext, ngettext

from .diffs import word_diff

INSERT, EDIT, MERGE, SPLIT = "insert", "edit", "merge", "split"


@dataclass(frozen=True)
class Line:
    """A sentence of a text being changed, or the title of a division (``level`` above 0)."""

    text: str
    starts_paragraph: bool = False
    level: int = 0


@dataclass(frozen=True)
class Applied:
    """The sentences after an operation: ``removed`` sentences from index ``start`` of the
    former list are replaced by ``added``."""

    lines: list
    start: int
    removed: int
    added: list


def apply_operation(lines, operation):
    """Apply an operation to a list of ``Line``; raise ValidationError if it does not apply.

    Operations, with normalized texts and 0-based indexes in ``lines``:
    ``{"kind": "insert", "before": i, "sentences": [{"text", "starts_paragraph"}]}``
    (``before`` equal to the number of lines adds at the end),
    ``{"kind": "edit", "index": i, "text", "starts_paragraph"}``,
    ``{"kind": "merge", "index": i}`` (with the next sentence),
    ``{"kind": "split", "index": i, "parts": [text, ...]}``.

    ``expected``, if given, lists the texts the operation was written against: those of the
    sentences it changes, or of the sentence an insertion follows (none at the start). Where
    they differ, the operation no longer applies: it would change another sentence.
    """
    kind = operation["kind"]
    expected = operation.get("expected")
    if kind == INSERT:
        start = operation["before"]
        if not 0 <= start <= len(lines):
            raise _missing()
        if expected is not None and expected != [
            line.text for line in lines[max(start - 1, 0) : start]
        ]:
            raise _missing()
        added = [
            Line(item["text"], item["starts_paragraph"], item["level"])
            for item in operation["sentences"]
        ]
        if not added:
            raise ValidationError(gettext("Ajoutez au moins une phrase."), code="empty")
        removed = 0
    else:
        start = operation["index"]
        removed = 2 if kind == MERGE else 1
        if not 0 <= start <= len(lines) - removed:
            raise _missing()
        if expected is not None and expected != [
            line.text for line in lines[start : start + removed]
        ]:
            raise _missing()
        line = lines[start]
        if kind == EDIT:
            added = [Line(operation["text"], operation["starts_paragraph"], line.level)]
            if not operation["text"]:
                raise ValidationError(gettext("Une phrase ne peut pas être vide."), code="empty")
            if added[0] == line:
                raise ValidationError(
                    gettext("Rien n’a changé dans cette phrase."), code="unchanged"
                )
        elif kind == MERGE:
            if line.level or lines[start + 1].level:
                raise ValidationError(
                    gettext("Un titre de division ne se fusionne pas avec une phrase."),
                    code="merge_heading",
                )
            added = [Line(f"{line.text} {lines[start + 1].text}", line.starts_paragraph)]
        else:
            parts = operation["parts"]
            if len(parts) < 2:
                raise ValidationError(
                    gettext("Coupez la phrase en au moins deux parties, une par ligne."),
                    code="one_part",
                )
            if " ".join(parts) != line.text:
                raise ValidationError(
                    gettext(
                        "Une scission ne change aucun mot : recollées, les parties doivent "
                        "redonner la phrase. Pour changer ses mots, modifiez la phrase."
                    ),
                    code="split_changed",
                )
            if line.level:
                raise ValidationError(
                    gettext("Un titre de division ne se scinde pas."), code="split_heading"
                )
            added = [
                Line(part, line.starts_paragraph and index == 0) for index, part in enumerate(parts)
            ]
    new_lines = [*lines[:start], *added, *lines[start + removed :]]
    return Applied(new_lines, start, removed, added)


def _missing():
    return ValidationError(
        gettext("Cette phrase n’existe plus dans le texte : rechargez la page."), code="missing"
    )


def simulate(lines, operations):
    """The sentences after operations applied in order; ValidationError if one does not apply."""
    for operation in operations:
        lines = apply_operation(lines, operation).lines
    return lines


def relocate(lines, operations):
    """(operations, lines): operations moved, where needed, to the single place where the
    texts they expect now are, and the sentences they give.

    Raise ValidationError when an operation has no such single place.
    """
    moved = []
    for operation in operations:
        operation = dict(operation)
        try:
            applied = apply_operation(lines, operation)
        except ValidationError:
            if operation.get("expected") is None:
                raise
            places = _places([line.text for line in lines], operation)
            if len(places) != 1:
                raise _missing() from None
            operation["before" if operation["kind"] == INSERT else "index"] = places[0]
            applied = apply_operation(lines, operation)
        moved.append(operation)
        lines = applied.lines
    return moved, lines


def _places(texts, operation):
    """The indexes where an operation finds the texts it expects."""
    expected = operation["expected"]
    if operation["kind"] == INSERT:
        if not expected:
            return [0]
        return [index + 1 for index, text in enumerate(texts) if text == expected[0]]
    size = len(expected)
    return [
        index for index in range(len(texts) - size + 1) if texts[index : index + size] == expected
    ]


def describe_operations(lines, operations):
    """Operations applied in order to ``lines``, as ``Described`` changes."""
    described = []
    for operation in operations:
        applied = apply_operation(lines, operation)
        start = applied.start
        removed = list(enumerate(lines[start : start + applied.removed], start=start + 1))
        added = list(enumerate(applied.added, start=start + 1))
        chunks = (
            word_diff(removed[0][1].text, added[0][1].text) if operation["kind"] == EDIT else []
        )
        described.append(Described(operation["kind"], removed, added, chunks))
        lines = applied.lines
    return described


@dataclass(frozen=True)
class Carried:
    """The Latin of a sentence, and who wrote it (None: the author of the version)."""

    text: str
    written_by_id: int | None = None


@dataclass(frozen=True)
class Described:
    """A change of the source text, made (``change``, a ``SourceChange``) or proposed.

    ``removed`` and ``added`` are (number, sentence) pairs, numbered as in the text before and
    after the change; ``chunks`` is the word diff of an edited sentence.
    """

    kind: str
    removed: list
    added: list
    chunks: list
    change: object = None

    @property
    def label(self):
        kind = self.kind
        if kind == INSERT:
            return ngettext(
                "Phrase %(first)d ajoutée", "Phrases %(first)d à %(last)d ajoutées", len(self.added)
            ) % {"first": self.added[0][0], "last": self.added[-1][0]}
        number = self.removed[0][0]
        if kind == EDIT:
            return gettext("Phrase %(number)d modifiée") % {"number": number}
        if kind == MERGE:
            return gettext("Phrases %(number)d et %(next)d fusionnées") % {
                "number": number,
                "next": self.removed[-1][0],
            }
        return gettext("Phrase %(number)d scindée en %(count)d") % {
            "number": number,
            "count": len(self.added),
        }


def is_active(segment, state):
    """Whether the sentence belongs to the text at this state."""
    return segment.added_in <= state and (segment.removed_in is None or segment.removed_in > state)


def carry(parts):
    """What the first new sentence receives from the removed ones: their Latin, joined.

    An edited sentence keeps its Latin and a split one leaves it on its first part; merged
    ones join theirs, credited to their writer if they share one, else to the author.
    """
    parts = [part for part in parts if part is not None and part.text]
    if not parts:
        return None
    writers = {part.written_by_id for part in parts}
    writer = writers.pop() if len(writers) == 1 else None
    return Carried(" ".join(part.text for part in parts), writer)


class SourceHistory:
    """All the sentences of a source text, removed ones included, loaded in one query."""

    def __init__(self, source_text):
        self.source_text = source_text
        self.state = source_text.state
        self.segments = list(source_text.segments.order_by("position"))
        self.by_id = {segment.pk: segment for segment in self.segments}
        self.added = defaultdict(list)
        self.removed = defaultdict(list)
        for segment in self.segments:
            self.added[segment.added_in].append(segment)
            if segment.removed_in is not None:
                self.removed[segment.removed_in].append(segment)

    def _state(self, state):
        return self.state if state is None else state

    def segments_at(self, state=None):
        """The sentences of the text at a state (by default, the current one), in order."""
        state = self._state(state)
        return [segment for segment in self.segments if is_active(segment, state)]

    def numbers_at(self, state=None):
        """{sentence id: number shown} at a state."""
        return {
            segment.pk: number for number, segment in enumerate(self.segments_at(state), start=1)
        }

    def carrier(self, segment):
        """The sentence that received the Latin of a removed sentence; None if not removed."""
        if segment.removed_in is None:
            return None
        return self.added[segment.removed_in][0]

    def resolve(self, segment_id, state=None):
        """The sentence that carries the Latin of a sentence at a later state.

        None when the sentence did not exist yet at that state.
        """
        state = self._state(state)
        segment = self.by_id.get(segment_id)
        if segment is None or segment.added_in > state:
            return None
        while segment.removed_in is not None and segment.removed_in <= state:
            segment = self.carrier(segment)
        return segment

    def origins(self, segment, state):
        """The sentences of an earlier state a sentence comes from; none for added text."""
        if segment.added_in <= state:
            return [segment]
        return [
            origin
            for removed in self.removed[segment.added_in]
            for origin in self.origins(removed, state)
        ]

    def project(self, texts, from_state, to_state=None):
        """The Latin of each sentence carried from one state of the text to a later one.

        ``texts`` maps sentence ids to ``Carried``; the result maps the sentences of the later
        state that have Latin.
        """
        texts = dict(texts)
        for number in range(from_state + 1, self._state(to_state) + 1):
            removed = self.removed[number]
            if not removed:
                continue
            carried = carry([texts.pop(segment.pk, None) for segment in removed])
            if carried is not None:
                texts[self.added[number][0].pk] = carried
        return texts

    def describe(self, from_state, to_state=None):
        """The changes of the text after ``from_state`` up to ``to_state``, in order."""
        to_state = self._state(to_state)
        if to_state <= from_state:
            return []
        changes = self.source_text.changes.filter(
            number__gt=from_state, number__lte=to_state
        ).select_related("author", "adopted_by")
        described = []
        before = self.numbers_at(from_state)
        for change in changes.order_by("number"):
            after = self.numbers_at(change.number)
            removed = [(before[segment.pk], segment) for segment in self.removed[change.number]]
            added = [(after[segment.pk], segment) for segment in self.added[change.number]]
            chunks = word_diff(removed[0][1].text, added[0][1].text) if change.kind == EDIT else []
            described.append(Described(change.kind, removed, added, chunks, change))
            before = after
        return described
