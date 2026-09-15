"""The reference form of a unit with the units it is made of marked in it.

``[rēs pūblica;rem pūblicam] administrāre`` names the unit *rēs pūblica*, written *rem pūblicam*
in the reference form *rem pūblicam administrāre*. The marked text is kept beside the plain
reference form, which every other use of the unit reads.
"""

import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.utils.translation import gettext

from corpus.text import normalize

from .composition import contains
from .models import Unit
from .schema import parse_schema
from .spotting import visible_units

MARK = re.compile(r"\[([^\[\];]*);([^\[\];]*)\]")
MAX_MARKS = 5
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
    return MARK.sub(
        lambda match: f"[{' '.join(match[1].split())};{' '.join(match[2].split())}]", text
    )


def segments(text):
    """The pieces of a marked reference form, in order."""
    parts, last = [], 0
    for match in MARK.finditer(text or ""):
        if match.start() > last:
            parts.append(Segment(text[last : match.start()]))
        parts.append(Segment(match[2], match[1]))
        last = match.end()
    if last < len(text or ""):
        parts.append(Segment(text[last:]))
    return parts


def name_key(name):
    """A name as it is compared: normalized, with single spaces."""
    return normalize(" ".join((name or "").split()))


def _letter(char):
    return f"[{LETTERS[char]}]" if char in LETTERS else re.escape(char)


def name_pattern(name, whole=True):
    """A regular expression for a name, whatever its macrons, its case, u or v, i or j."""
    key, pieces, index = name_key(name), [], 0
    while index < len(key):
        pair = key[index : index + 2]
        if pair in LIGATURES:
            pieces.append(f"(?:{_letter(pair[0])}{_letter(pair[1])}|{LIGATURES[pair]})")
            index += 2
            continue
        pieces.append(r"\s+" if key[index] == " " else _letter(key[index]))
        index += 1
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
    return parts
