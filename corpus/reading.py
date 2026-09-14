"""Reading a work from end to end: its pages, the headings in them, the translation beside.

A page holds consecutive divisions of a work up to ``PAGE_SIZE`` characters of Latin: a
whole book of De officiis, several letters of Seneca. A division too long for a page is
split into its own divisions: a book of Livy into groups of chapters.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import groupby

from django.db.models.functions import Length
from django.utils.translation import gettext_lazy as _

# About 16,000 words: the longest book of De officiis fits.
PAGE_SIZE = 100_000

# Labels of the citation levels of the editions: one division, then a range of them.
LEVELS = {
    "actio": (_("action %(value)s"), _("actions %(first)s à %(last)s")),
    "book": (_("livre %(value)s"), _("livres %(first)s à %(last)s")),
    "chapter": (_("chapitre %(value)s"), _("chapitres %(first)s à %(last)s")),
    "fragment": (_("fragment %(value)s"), _("fragments %(first)s à %(last)s")),
    "letter": (_("lettre %(value)s"), _("lettres %(first)s à %(last)s")),
    "line": (_("vers %(value)s"), _("vers %(first)s à %(last)s")),
    "poem": (_("poème %(value)s"), _("poèmes %(first)s à %(last)s")),
    "section": (_("section %(value)s"), _("sections %(first)s à %(last)s")),
    "speech": (_("discours %(value)s"), _("discours %(first)s à %(last)s")),
    "topic": (_("sujet %(value)s"), _("sujets %(first)s à %(last)s")),
}


def capitalized(text):
    return text[:1].upper() + text[1:]


def _labels(scheme, level):
    name = scheme[level] if level < len(scheme) else ""
    return LEVELS.get(name) or (f"{name} %(value)s".strip(), f"{name} %(first)s–%(last)s".strip())


def division_label(scheme, level, value):
    return str(_labels(scheme, level)[0]) % {"value": value}


def range_label(scheme, level, first, last):
    return str(_labels(scheme, level)[1]) % {"first": first, "last": last}


def _value(reference, level):
    """The value of a reference at a level: 12 at the second level of 1.12.3."""
    levels = reference.split(".")
    return levels[level] if level < len(levels) else ""


@dataclass(frozen=True)
class Page:
    """Consecutive passages read together, from the order ``start`` to the order ``end``.

    ``parent`` holds the reference levels its passages share; ``first`` and ``last`` are the
    values, at the next level, of its first and last divisions. The whole work has neither.
    """

    start: int
    end: int
    parent: tuple = ()
    first: str = ""
    last: str = ""
    whole: bool = False

    @property
    def key(self):
        if self.whole:
            return ""
        first = ".".join((*self.parent, self.first))
        if self.first == self.last:
            return first
        return f"{first}-{'.'.join((*self.parent, self.last))}"

    @property
    def depth(self):
        """How many reference levels the title of the page already names."""
        if self.whole:
            return 0
        return len(self.parent) + (self.first == self.last)

    def label(self, scheme):
        if self.whole:
            return ""
        parts = [division_label(scheme, level, value) for level, value in enumerate(self.parent)]
        level = len(self.parent)
        if self.first == self.last:
            parts.append(division_label(scheme, level, self.first))
        else:
            parts.append(range_label(scheme, level, self.first, self.last))
        return capitalized(", ".join(parts))


def plan_pages(rows, levels, size=None):
    """The pages of a work, from (order, reference, characters) of its passages in order."""
    size = size or PAGE_SIZE
    rows = list(rows)
    if not rows:
        return []
    if sum(row[2] for row in rows) <= size:
        return [Page(rows[0][0], rows[-1][0], whole=True)]
    return _pack(rows, (), max(levels, 1), size)


def _pack(rows, parent, levels, size):
    """Pack the divisions of ``rows`` at the level under ``parent`` into pages."""
    level = len(parent)
    pages, batch, batch_size = [], [], 0

    def page_of(batch):
        return Page(batch[0][1][0][0], batch[-1][1][-1][0], parent, batch[0][0], batch[-1][0])

    for value, group in groupby(rows, key=lambda row: _value(row[1], level)):
        group = list(group)
        group_size = sum(row[2] for row in group)
        if group_size > size and level + 1 < levels and len(group) > 1:
            if batch:
                pages.append(page_of(batch))
                batch, batch_size = [], 0
            pages += _pack(group, (*parent, value), levels, size)
            continue
        if batch and batch_size + group_size > size:
            pages.append(page_of(batch))
            batch, batch_size = [], 0
        batch.append((value, group))
        batch_size += group_size
    if batch:
        pages.append(page_of(batch))
    return pages


@dataclass
class ReadingPlan:
    """The pages of an edition, and its first divisions with their first passage."""

    scheme: list
    pages: list
    divisions: list = field(default_factory=list)  # (value, reference, order)

    def page_at(self, order):
        starts = [page.start for page in self.pages]
        return self.pages[max(bisect_right(starts, order) - 1, 0)]

    def page(self, key):
        return next((page for page in self.pages if page.key == key), None)


def reading_plan(edition):
    rows = list(
        edition.passages.annotate(size=Length("text"))
        .order_by("order")
        .values_list("order", "reference", "size")
    )
    scheme = list(edition.citation_scheme or [])
    divisions = []
    if len(scheme) > 1:
        for value, group in groupby(rows, key=lambda row: _value(row[1], 0)):
            order, reference, _size = next(group)
            divisions.append((value, reference, order))
    return ReadingPlan(scheme, plan_pages(rows, len(scheme)), divisions)


@dataclass
class Item:
    passage: object
    tokens: list
    headings: list
    number: str
    quiet: bool = False


@dataclass
class Row:
    """Passages of a page shown beside one part of the translation, or none."""

    items: list
    part: object = None


def reading_rows(page, scheme, passages, tokens, parts, verse=False):
    """The rows of a page: passages with the headings of the divisions they begin.

    ``tokens`` maps passage identifiers to their words, ``parts`` references to the part of
    the translation shown beside them. Verse lines are numbered every five lines.
    """
    levels = max(len(scheme), 1)
    seen = {}
    items = []
    for passage in passages:
        headings = []
        for level in range(page.depth, levels - 1):
            prefix = tuple(passage.reference.split(".")[: level + 1])
            value = _value(passage.reference, level)
            if value and seen.get(level) != prefix:
                headings.append(capitalized(division_label(scheme, level, value)))
            seen[level] = prefix
        number = passage.reference.split(".")[-1]
        quiet = verse and number.isdigit() and int(number) % 5 != 0
        items.append(Item(passage, tokens.get(passage.pk, []), headings, number, quiet))
    return [
        Row(list(group), part)
        for part, group in groupby(items, key=lambda item: parts.get(item.passage.reference))
    ]
