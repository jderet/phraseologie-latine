"""Reading Perseus TEI editions (canonical-latinLit) as passages of words.

The files come from a local clone of the Perseus repository, a trusted source; they are
parsed with the standard library, whose expat parser does not load external entities.
"""

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from .text import TextToken, tokenize

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

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


class PerseusError(ValueError):
    pass


@dataclass
class ParsedPassage:
    reference: str
    text: str
    tokens: list[TextToken]
    heading: str = ""


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


class TextBuilder:
    """Collects the text of TEI elements with single spaces, remembering foreign spans."""

    def __init__(self):
        self._parts = []
        self._length = 0
        self._space_pending = False
        self._foreign_spans = []

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
        if name == "choice":
            readings = {_name(child): child for child in element}
            chosen = next((readings[n] for n in CHOICE_PREFERENCE if n in readings), None)
            if chosen is None and len(element):
                chosen = element[0]
            if chosen is not None:
                self.add_element(chosen, foreign)
            return
        if name == "foreign" and (element.get(XML_LANG) or "").lower() in GREEK_LANGUAGES:
            foreign = True
        self.add_text(element.text, foreign)
        for child in element:
            self.add_element(child, foreign)
            self.add_text(child.tail, foreign)
        if name in BLOCK_ELEMENTS:
            self.add_space()

    def passage(self, reference, heading=""):
        text = "".join(self._parts)
        tokens = []
        offset = 0
        for token in tokenize(text):
            start = offset + len(token.before)
            end = start + len(token.form)
            offset = end + len(token.after)
            if not token.is_foreign and any(s < end and start < e for s, e in self._foreign_spans):
                token = replace(token, is_foreign=True)
            tokens.append(token)
        return ParsedPassage(reference, text, tokens, heading)

    def _append(self, value):
        self._parts.append(value)
        self._length += len(value)


def _headings(element):
    heads = (" ".join("".join(head.itertext()).split()) for head in element.findall(f"{TEI}head"))
    return _join(*heads)


def _textparts(element):
    return [child for child in element if _name(child) == "div" and child.get("type") == "textpart"]


def _is_editorial(division):
    labels = {(division.get("subtype") or "").lower(), (division.get("n") or "").lower()}
    return bool(labels & SKIPPED_DIVISIONS)


def _textpart_passages(edition, wrappers):
    """Passages of a prose edition: its deepest textpart divisions.

    ``wrappers`` is the number of upper division levels that the CTS citation skips.
    """
    passages = []
    scheme = []

    def walk(element, depth, references, subtypes, heading):
        heading = _join(heading, _headings(element))
        divisions = _textparts(element)
        if not divisions:
            if depth:
                if not scheme:
                    scheme.extend(subtypes)
                builder = TextBuilder()
                builder.add_element(element)
                passages.append(builder.passage(".".join(references), heading))
            return
        first = True
        for division in divisions:
            if _is_editorial(division):
                continue
            number = division.get("n")
            cited = depth >= wrappers and bool(number)
            walk(
                division,
                depth + 1,
                [*references, number] if cited else references,
                [*subtypes, division.get("subtype") or ""] if cited else subtypes,
                heading if first else "",
            )
            first = False

    walk(edition, 0, [], [], "")
    return passages, scheme


def _line_passages(edition):
    """Passages of a verse edition: numbered lines; an unnumbered line joins the previous one."""
    ignored = {
        inner
        for element in edition.iter()
        if _name(element) in SKIPPED_ELEMENTS
        for inner in element.iter()
    }
    groups = []
    for line in edition.iter(f"{TEI}l"):
        if line in ignored:
            continue
        number = line.get("n")
        if number or not groups:
            groups.append((number or "0", [line]))
        else:
            groups[-1][1].append(line)
    passages = []
    for reference, lines in groups:
        builder = TextBuilder()
        for line in lines:
            builder.add_element(line)
        passages.append(builder.passage(reference))
    return passages


def read_edition(path, exclude=""):
    """Read a Perseus edition; passages whose reference fully matches ``exclude`` are left out."""
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - trusted local files, see module docstring
    except ET.ParseError as error:
        raise PerseusError(f"{Path(path).name}: {error}") from error
    edition = root.find(f"{TEI}text/{TEI}body/{TEI}div[@type='edition']")
    if edition is None:
        raise PerseusError(f'{Path(path).name}: no <div type="edition">')
    patterns = sorted(
        (
            (pattern.get("replacementPattern") or "").count("$"),
            pattern.get("n"),
            pattern.get("replacementPattern") or "",
        )
        for pattern in root.iter(f"{TEI}cRefPattern")
    )
    if any("tei:l[" in replacement for _count, _name_, replacement in patterns):
        passages, scheme = _line_passages(edition), ["line"]
    else:
        shortest = patterns[0][2] if patterns else ""
        if "[@n=" in shortest:
            wrappers = max(shortest.split("[@n=")[0].count("tei:div") - 2, 0)
        else:
            wrappers = 0
        passages, subtypes = _textpart_passages(edition, wrappers)
        names = [name for _count, name, _replacement in patterns]
        scheme = names if names and all(names) else subtypes
    if exclude:
        excluded = re.compile(exclude)
        passages = [p for p in passages if not excluded.fullmatch(p.reference)]
    return ParsedEdition(edition.get("n", ""), scheme, passages)


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
