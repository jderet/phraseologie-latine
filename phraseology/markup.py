"""The reference form of a unit with the units it is made of marked in it.

``[rēs pūblica;rem pūblicam] administrāre`` names the unit *rēs pūblica*, written *rem pūblicam*
in the reference form *rem pūblicam administrāre*. The marked text is kept beside the plain
reference form, which every other use of the unit reads.

An abstract word stays in the plain reference form, between braces: ``{liquide} sūmere``. It
is shown with its label and a link to its page.
"""

import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.utils.translation import gettext

from corpus.text import normalize
from moderation.registry import can_view

from .abstract import WRITTEN as ABSTRACT
from .abstract import clean_name
from .composition import contains
from .models import AbstractWord, Unit
from .schema import parse_schema
from .spotting import visible_units

MARK = re.compile(r"\[([^\[\];]*);([^\[\];]*)\]")
# A mark or an abstract word, in the order of the text.
PIECE = re.compile(f"{MARK.pattern}|{ABSTRACT.pattern}")
MAX_MARKS = 5
MAX_ABSTRACTS = 3
# A marked unit may have homonyms; a few are named in its bubble.
MAX_HOMONYMS = 5
STATUS_ORDER = {
    Unit.Status.VALIDATED: 0,
    Unit.Status.PROPOSED: 1,
    Unit.Status.CONTESTED: 2,
    Unit.Status.DRAFT: 3,
}
# The letters a normalized letter stands for, whatever the macrons or the spelling (v, j).
LETTERS = {
    "a": "aāăáàâä",
    "e": "eēĕéèêë",
    "i": "iījĭíìîï",
    "o": "oōŏóòôö",
    "u": "uūŭúùûüv",
    "y": "yȳýÿ",
}
LIGATURES = {"ae": "æ", "oe": "œ"}


@dataclass
class Segment:
    """A piece of a reference form: plain words, or the words of a unit it names."""

    text: str
    name: str = ""
    unit: object = None
    others: list = field(default_factory=list)
    # The name of an abstract word, and the word itself if the reader may see it.
    abstract: str = ""
    word: object = None


def plain_form(text):
    """The reference form without its marks: the words as they are written."""
    return MARK.sub(lambda match: match[2], text or "")


def clean_marks(text):
    """The marks of a text written again with single spaces; raise ValidationError if one is
    not written [name;words]."""
    text = text or ""
    if "[" in MARK.sub("", text) or "]" in MARK.sub("", text):
        raise ValidationError(
            gettext("Marquez une fiche ainsi, crochets fermés : [rēs pūblica;rem pūblicam]."),
            code="mark",
        )
    marks = MARK.findall(text)
    if any(not name.strip() or not words.strip() for name, words in marks):
        raise ValidationError(
            gettext(
                "Entre crochets, écrivez le nom de la fiche, un point-virgule, puis ses mots "
                "dans cette forme : [rēs pūblica;rem pūblicam]."
            ),
            code="mark_empty",
        )
    if len(marks) > MAX_MARKS:
        raise ValidationError(
            gettext("Une forme de référence marque au plus %(limit)d fiches.")
            % {"limit": MAX_MARKS},
            code="too_many_marks",
        )
    bare = MARK.sub("", text)
    if "{" in ABSTRACT.sub("", bare) or "}" in ABSTRACT.sub("", bare):
        raise ValidationError(
            gettext("Écrivez un mot abstrait entre accolades fermées : {liquide} sūmere."),
            code="abstract",
        )
    names = [clean_name(name) for name in ABSTRACT.findall(bare)]
    if len(names) > MAX_ABSTRACTS:
        raise ValidationError(
            gettext("Une forme de référence compte au plus %(limit)d mots abstraits.")
            % {"limit": MAX_ABSTRACTS},
            code="too_many_abstracts",
        )
    text = MARK.sub(
        lambda match: f"[{' '.join(match[1].split())};{' '.join(match[2].split())}]", text
    )
    return ABSTRACT.sub(lambda match: f"{{{clean_name(match[1])}}}", text)


def form_abstracts(text):
    """The names of the abstract words of a reference form, outside its marks."""
    return ABSTRACT.findall(MARK.sub("", text or ""))


def is_marked(text):
    """Whether a reference form marks a unit or names an abstract word: it is then kept marked."""
    return bool(MARK.search(text or "") or ABSTRACT.search(MARK.sub("", text or "")))


def segments(text):
    """The pieces of a marked reference form, in order."""
    parts, last = [], 0
    for match in PIECE.finditer(text or ""):
        if match.start() > last:
            parts.append(Segment(text[last : match.start()]))
        if match[3] is not None:
            parts.append(Segment(match[0], abstract=match[3]))
        else:
            parts.append(Segment(match[2], match[1]))
        last = match.end()
    if last < len(text or ""):
        parts.append(Segment(text[last:]))
    return parts


def name_key(name):
    """A name as it is compared: normalized, with single spaces, without the braces of its
    abstract words: {liquide} sūmere is found as liquide sumere."""
    return normalize(" ".join((name or "").replace("{", "").replace("}", "").split()))


def _letter(char):
    return f"[{LETTERS[char]}]" if char in LETTERS else re.escape(char)


def name_pattern(name, whole=True):
    """A regular expression for a name, whatever its macrons, its case, u or v, i or j, and
    the braces of its abstract words."""
    key, pieces, index = name_key(name), [r"\{?"], 0
    while index < len(key):
        pair = key[index : index + 2]
        if pair in LIGATURES:
            pieces.append(f"(?:{_letter(pair[0])}{_letter(pair[1])}|{LIGATURES[pair]})")
            index += 2
            continue
        if key[index] == " ":
            pieces.append(r"\}?\s+\{?")
        else:
            pieces.append(_letter(key[index]))
        index += 1
    pieces.append(r"\}?")
    pattern = "".join(pieces)
    return f"^{pattern}$" if whole else pattern


def units_named(user, name):
    """The units the user may see whose reference form is this name."""
    key = name_key(name)
    if not key:
        return []
    units = visible_units(user).filter(reference_form__iregex=name_pattern(name))
    return [unit for unit in units if name_key(unit.reference_form) == key]


def _within(unit, edges):
    try:
        return contains(edges, parse_schema(unit.schema))
    except ValidationError:
        return False


def resolve(user, text, edges=(), exclude=None):
    """The pieces of a marked reference form, each mark with the unit it most likely names.

    Among units of the same name, the one whose schema is part of ``edges`` comes first, then
    the validated one; the others stay listed. A draft is found by its author only.
    """
    parts = segments(text)
    found = {}
    for part in parts:
        key = name_key(part.name)
        if not part.name or key in found:
            continue
        units = [unit for unit in units_named(user, part.name) if unit != exclude]
        found[key] = sorted(
            units,
            key=lambda unit: (
                not _within(unit, edges),
                STATUS_ORDER.get(unit.status, len(STATUS_ORDER)),
                unit.pk,
            ),
        )
    for part in parts:
        if part.name:
            units = found[name_key(part.name)]
            part.unit = units[0] if units else None
            part.others = units[1 : 1 + MAX_HOMONYMS]
    names = {part.abstract for part in parts if part.abstract}
    if names:
        words = {
            word.name: word
            for word in AbstractWord.objects.filter(name__in=names)
            if can_view(user, word)
        }
        for part in parts:
            if part.abstract:
                part.word = words.get(part.abstract)
    return parts
