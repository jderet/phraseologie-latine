"""Reading Perseus TEI editions (canonical-latinLit) as passages of words.

The files come from a local clone of the Perseus repository, a trusted source; they are
parsed with the standard library, whose expat parser does not load external entities.
"""

import html.entities
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from .text import TextToken, tokenize

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
URN_PREFIX = "urn:cts:latinLit:"

# Elements whose content is not the author's text.
SKIPPED_ELEMENTS = {
    "note",
    "bibl",
    "head",
    "speaker",
    "stage",
    "label",
    "figure",
    "rdg",
    "del",
    "castList",
    "fw",
}
# Elements after which a space separates the words.
BLOCK_ELEMENTS = {"p", "l", "lg", "sp", "ab", "div", "list", "item"}
# Reading kept in a <choice>: the correction, the original spelling, the abbreviation as printed.
CHOICE_PREFERENCE = ("corr", "orig", "abbr")
# Divisions written by the editor, not by the author.
SKIPPED_DIVISIONS = {"index", "sigla"}
GREEK_LANGUAGES = {"grc", "greek", "gr", "el"}
# Older files number their divisions (div1, div2…) instead of marking them as textparts.
NUMBERED_DIVISION = re.compile(r"div[1-7]")
# Some files use HTML entities (&dagger;) without declaring them.
ENTITY_PATTERN = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = {b"amp", b"lt", b"gt", b"quot", b"apos"}


class PerseusError(ValueError):
    pass


@dataclass
class ParsedPassage:
    reference: str
    text: str
    tokens: list[TextToken]
    heading: str = ""
    speaker: str = ""


@dataclass
class ParsedEdition:
    urn: str
    citation_scheme: list[str]
    passages: list[ParsedPassage] = field(default_factory=list)

    @property
    def token_count(self):
        return sum(len(passage.tokens) for passage in self.passages)


def _name(element):
    return element.tag.rsplit("}", 1)[-1]


def _join(*parts):
    return " · ".join(part for part in parts if part)


def _passage(text, foreign_spans, reference, heading, speaker=""):
    tokens = []
    offset = 0
    for token in tokenize(text):
        start = offset + len(token.before)
        end = start + len(token.form)
        offset = end + len(token.after)
        if not token.is_foreign and any(s < end and start < e for s, e in foreign_spans):
            token = replace(token, is_foreign=True)
        tokens.append(token)
    return ParsedPassage(reference, text, tokens, heading, speaker)


class TextBuilder:
    """Collects the text of TEI elements with single spaces, remembering foreign spans.

    It also notes where numbered milestones stand, so that the text can be cut there.
    """

    def __init__(self):
        self._parts = []
        self._length = 0
        self._space_pending = False
        self._foreign_spans = []
        self.milestones = []

    def add_text(self, value, foreign=False):
        if not value:
            return
        value = unicodedata.normalize("NFC", value)
        if value[0].isspace():
            self._space_pending = True
        words = value.split()
        if not words:
            return
        if self._space_pending and self._length:
            self._append(" ")
        start = self._length
        self._append(" ".join(words))
        if foreign:
            self._foreign_spans.append((start, self._length))
        self._space_pending = value[-1].isspace()

    def add_space(self):
        self._space_pending = True

    def add_element(self, element, foreign=False):
        name = _name(element)
        if name in SKIPPED_ELEMENTS:
            return
        if name == "milestone" and element.get("n"):
            self.milestones.append((self._length, element.get("unit") or "", element.get("n")))
        if name == "choice":
            readings = {_name(child): child for child in element}
            chosen = next((readings[n] for n in CHOICE_PREFERENCE if n in readings), None)
            if chosen is None and len(element):
                chosen = element[0]
            if chosen is not None:
                self.add_element(chosen, foreign)
            return
        language = (element.get(XML_LANG) or element.get("lang") or "").lower()
        if name == "foreign" and language in GREEK_LANGUAGES:
            foreign = True
        self.add_text(element.text, foreign)
        for child in element:
            self.add_element(child, foreign)
            self.add_text(child.tail, foreign)
        if name in BLOCK_ELEMENTS:
            self.add_space()

    def passage(self, reference, heading="", speaker=""):
        return _passage("".join(self._parts), self._foreign_spans, reference, heading, speaker)

    def milestone_passages(self, references, heading="", unit="", speaker=""):
        """Passages cut at the milestones of ``unit``, or of the first unit met.

        The text before the first milestone joins the first passage.
        """
        unit = unit or self.milestones[0][1]
        cuts = [(offset, number) for offset, kind, number in self.milestones if kind == unit]
        text = "".join(self._parts)
        passages = []
        for index, (offset, number) in enumerate(cuts):
            start = 0 if index == 0 else offset
            end = cuts[index + 1][0] if index + 1 < len(cuts) else len(text)
            piece = text[start:end]
            lead = len(piece) - len(piece.lstrip())
            piece = piece.strip()
            shift = start + lead
            spans = [(s - shift, e - shift) for s, e in self._foreign_spans]
            passages.append(
                _passage(
                    piece,
                    spans,
                    ".".join([*references, number]),
                    heading if not index else "",
                    speaker,
                )
            )
        return unit, passages

    def _append(self, value):
        self._parts.append(value)
        self._length += len(value)


def _headings(element):
    heads = (
        " ".join("".join(head.itertext()).split()) for head in element if _name(head) == "head"
    )
    return _join(*heads)


def _is_textpart(element):
    name = _name(element)
    if name == "div":
        return element.get("type") == "textpart"
    return bool(NUMBERED_DIVISION.fullmatch(name))


def _subtype(division):
    return division.get("subtype" if _name(division) == "div" else "type") or ""


def _textparts(element):
    return [child for child in element if _is_textpart(child)]


def _is_editorial(division):
    labels = {_subtype(division).lower(), (division.get("n") or "").lower()}
    return bool(labels & SKIPPED_DIVISIONS)


def _numbered_segments(element):
    """Numbered <seg> elements of a division, outside notes and other skipped elements."""
    segments = []
    for child in element:
        if _name(child) in SKIPPED_ELEMENTS:
            continue
        if _name(child) == "seg" and child.get("n"):
            segments.append(child)
        else:
            segments.extend(_numbered_segments(child))
    return segments


def _textpart_passages(
    edition,
    wrappers,
    sections=False,
    milestones=False,
    milestone_unit="",
    uncited=(),
    renumber=False,
):
    """Passages of a prose edition: its deepest textpart divisions.

    ``wrappers`` is the number of upper division levels that the CTS citation skips. With
    ``sections``, a division whose text is in numbered <seg> elements gives one passage per
    segment; with ``milestones``, a division is cut at its numbered milestones, of
    ``milestone_unit`` if given. Divisions whose subtype is in ``uncited`` are left out of
    references. With ``renumber``, a division numbered like an earlier sibling follows the
    previous number (a third book numbered 1 again, for example).
    """
    passages = []
    scheme = []

    def leaf(element, references, subtypes, heading):
        segments = _numbered_segments(element) if sections else []
        if segments:
            scheme[:] = scheme or [*subtypes, "section"]
            for index, segment in enumerate(segments):
                builder = TextBuilder()
                builder.add_element(segment)
                reference = ".".join([*references, segment.get("n")])
                passages.append(builder.passage(reference, heading if not index else ""))
            return
        builder = TextBuilder()
        builder.add_element(element)
        if milestone_unit and not any(
            kind == milestone_unit for _o, kind, _n in builder.milestones
        ):
            builder.milestones = []
        if milestones and builder.milestones:
            unit, cut = builder.milestone_passages(references, heading, milestone_unit)
            scheme[:] = scheme or [*subtypes, unit]
            passages.extend(cut)
            return
        scheme[:] = scheme or subtypes
        passages.append(builder.passage(".".join(references), heading))

    def walk(element, depth, references, subtypes, heading):
        heading = _join(heading, _headings(element))
        divisions = _textparts(element)
        if not divisions:
            # Without divisions, a text cut at milestones is cited by them alone.
            if depth or milestone_unit:
                leaf(element, references, subtypes, heading)
            return
        first = True
        previous = None
        seen = set()
        for division in divisions:
            if _is_editorial(division):
                continue
            number = division.get("n")
            repeated = renumber and number in seen
            # A division left unnumbered between numbered ones follows the previous number.
            if (not number or repeated) and depth >= wrappers and previous and previous.isdigit():
                number = str(int(previous) + 1)
            previous = number
            seen.add(number)
            cited = depth >= wrappers and bool(number) and _subtype(division).lower() not in uncited
            walk(
                division,
                depth + 1,
                [*references, number] if cited else references,
                [*subtypes, _subtype(division)] if cited else subtypes,
                heading if first else "",
            )
            first = False

    walk(edition, 0, [], [], "")
    return passages, scheme


def _cited_depths(replacement):
    """Depths of the divisions (the edition being 0) that a line citation names."""
    steps = [step for step in re.split(r"/+", replacement.split("tei:body", 1)[-1]) if step]
    depths = []
    for depth, step in enumerate(steps):
        if not step.startswith("tei:div"):
            break
        if "[@n=" in step:
            depths.append(depth)
    return depths


def _speaker(element):
    """The name in the <speaker> of a <sp> element, with single spaces."""
    for child in element:
        if _name(child) == "speaker":
            text = " ".join("".join(child.itertext()).split())
            if text:
                return text
    return ""


def _scene_heading(context):
    """The act and scene a line opens, for a play, or nothing.

    ``context`` holds the (number, subtype) of the textpart divisions around the line; only
    the act and scene levels of a play are named, so other editions get no heading here.
    Front matter (a division numbered « front ») is left unlabelled.
    """
    parts = []
    for number, subtype in context:
        if subtype == "act":
            if number == "prologue":
                parts.append("Prologue")
            elif number.isdigit():
                parts.append(f"Acte {number}")
        elif subtype == "scene" and number != "pr":
            parts.append(f"Scène {number}")
    return " · ".join(parts)


def _line_passages(edition, depths=()):
    """Passages of a verse edition: numbered lines; an unnumbered line joins the previous one.

    ``depths`` are the division levels whose numbers come before the line number, as in
    book.line; line numbers start again in each of them. A play keeps the name of its speaker
    and a heading on the first line of each scene.
    """
    groups = []
    subtypes = []

    def walk(element, path, speaker):
        if _name(element) == "sp":
            speaker = _speaker(element) or speaker
        for child in element:
            name = _name(child)
            if name in SKIPPED_ELEMENTS:
                continue
            if name == "l":
                cited = [path[depth] for depth in depths if depth < len(path)]
                prefix = [number for number, _subtype in cited if number]
                number = child.get("n")
                if number or not groups or groups[-1][0] != prefix:
                    subtypes[:] = subtypes or [subtype for _number, subtype in cited]
                    groups.append((prefix, number or "0", [child], tuple(path[1:]), speaker))
                else:
                    groups[-1][2].append(child)
            elif _name(child) == "div" and child.get("type") == "textpart":
                walk(child, [*path, (child.get("n") or "", child.get("subtype") or "")], speaker)
            else:
                walk(child, path, speaker)

    walk(edition, [("", "")], "")
    passages = []
    seen = None
    for prefix, number, lines, context, speaker in groups:
        builder = TextBuilder()
        for line in lines:
            builder.add_element(line)
        heading = "" if context == seen else _scene_heading(context)
        passages.append(
            builder.passage(".".join([*prefix, number]), heading=heading, speaker=speaker)
        )
        seen = context
    return passages, [*subtypes, "line"]


def _character_references(data):
    """Undeclared HTML entities written as character references, which XML always knows."""

    def replace_entity(match):
        name = match.group(1)
        character = html.entities.html5.get(name.decode("ascii") + ";")
        if name in XML_ENTITIES or character is None:
            return match.group(0)
        return "".join(f"&#{ord(char)};" for char in character).encode("ascii")

    return ENTITY_PATTERN.sub(replace_entity, data)


def _parse(path):
    data = _character_references(Path(path).read_bytes())
    try:
        return ET.fromstring(data)  # noqa: S314 - trusted local files, see module docstring
    except ET.ParseError as error:
        raise PerseusError(f"{Path(path).name}: {error}") from error


def read_edition(path, exclude=""):
    """Read a Perseus edition; passages whose reference fully matches ``exclude`` are left out."""
    root = _parse(path)
    edition = root.find(f"{TEI}text/{TEI}body/{TEI}div[@type='edition']")
    if edition is not None:
        urn = edition.get("n", "")
        passages, scheme = _cited_passages(root, edition)
    else:
        # An older file: numbered divisions in the body, chapters sometimes marked by milestones.
        body = next((element for element in root.iter() if _name(element) == "body"), None)
        if body is None or not _textparts(body):
            raise PerseusError(f'{Path(path).name}: no <div type="edition">')
        urn = URN_PREFIX + Path(path).stem
        passages, scheme = _textpart_passages(body, 0, milestones=True)
    if exclude:
        excluded = re.compile(exclude)
        passages = [p for p in passages if not excluded.fullmatch(p.reference)]
    return ParsedEdition(urn, scheme, passages)


def read_translation(path, milestone="", uncited=(), exclude=""):
    """Read a Perseus translation, cut as its citation patterns say, or at ``milestone``s.

    ``uncited`` lists division subtypes left out of references (a chapter grouping sections
    numbered through a book, for example).
    """
    root = _parse(path)
    body = f"{TEI}text/{TEI}body/{TEI}div"
    division = root.find(f"{body}[@type='translation']")
    if division is None:
        division = root.find(f"{body}[@type='edition']")
    if division is None:
        # Some older files put the text right in the body.
        division = next((element for element in root.iter() if _name(element) == "body"), None)
    if division is None:
        raise PerseusError(f'{Path(path).name}: no <div type="translation">')
    if milestone:
        passages, scheme = _textpart_passages(
            division,
            0,
            milestones=True,
            milestone_unit=milestone,
            uncited=uncited,
            renumber=True,
        )
    else:
        passages, scheme = _cited_passages(root, division)
    if exclude:
        excluded = re.compile(exclude)
        passages = [p for p in passages if not excluded.fullmatch(p.reference)]
    return ParsedEdition(division.get("n", ""), scheme, passages)


def _cited_passages(root, edition):
    """Passages of an edition cut as its CTS citation patterns describe."""
    patterns = sorted(
        (
            (pattern.get("replacementPattern") or "").count("$"),
            pattern.get("n"),
            pattern.get("replacementPattern") or "",
        )
        for pattern in root.iter(f"{TEI}cRefPattern")
    )
    names = [name for _count, name, _replacement in patterns]
    lines = [replacement for _count, _name_, replacement in patterns if "tei:l[" in replacement]
    if lines:
        depths = _cited_depths(lines[-1])
        passages, subtypes = _line_passages(edition, depths)
        if names and all(names) and len(names) == len(depths) + 1:
            return passages, [name.lower() for name in names]
        return passages, subtypes
    shortest = patterns[0][2] if patterns else ""
    if "[@n=" in shortest:
        wrappers = max(shortest.split("[@n=")[0].count("tei:div") - 2, 0)
    else:
        wrappers = 0
    sections = any("tei:seg[" in replacement for _count, _name_, replacement in patterns)
    passages, subtypes = _textpart_passages(edition, wrappers, sections=sections)
    return passages, names if names and all(names) else subtypes


def git_revision(repository):
    """Commit checked out in a Git clone, read from its .git directory."""
    git_dir = Path(repository) / ".git"
    head = (git_dir / "HEAD").read_text().strip()
    if not head.startswith("ref: "):
        return head
    ref = head.removeprefix("ref: ")
    if (git_dir / ref).is_file():
        return (git_dir / ref).read_text().strip()
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            if line.endswith(f" {ref}"):
                return line.split(" ", 1)[0]
    raise PerseusError(f"Git reference {ref} not found in {git_dir}")
