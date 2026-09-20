"""Splitting a source text into sentences.

The split is only a proposal: the person who adds a text checks it, one sentence per line,
before saving. A line break always ends a sentence; a blank line starts a new paragraph.

A line written with one to three ``#`` is the title of a division: a part, a chapter, a
section. It is never split, and the text starts a new paragraph after it.
"""

import re
import unicodedata
from dataclasses import dataclass

MAX_SENTENCES = 2000
MAX_LEVEL = 3
MAX_SENTENCE_LENGTH = 2000

# Words that end with a period without ending the sentence, compared in lower case.
# fmt: off
ABBREVIATIONS = {
    "fr": {
        "m", "mm", "mme", "mmes", "mlle", "mlles", "mgr", "dr", "pr", "me", "st", "ste",
        "p", "pp", "cf", "ex", "av", "apr", "env", "vol", "chap", "éd", "n", "no", "art",
        "fig", "ibid", "op", "cit", "s", "sq", "sqq", "t", "col", "coll", "trad", "hab",
    },
    "en": {
        "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "e.g", "i.e", "cf", "p",
        "pp", "no", "vol", "ch", "ed", "eds", "fig", "approx", "ca", "c", "gen", "col",
    },
    "de": {
        "hr", "fr", "dr", "prof", "st", "z.b", "d.h", "u.a", "usw", "bzw", "vgl", "ca",
        "s", "bd", "nr", "jh", "chr", "v", "n", "geb", "gest", "evtl", "sog", "u.ä",
    },
    "it": {
        "sig", "sigg", "sig.ra", "dott", "prof", "ing", "avv", "s", "ss", "p", "pp", "cfr",
        "ecc", "es", "vol", "cap", "n", "a.c", "d.c", "sec",
    },
    "es": {
        "sr", "sra", "srta", "dr", "dra", "d", "dña", "prof", "p", "pp", "pág", "págs",
        "cf", "vol", "cap", "núm", "n", "a.c", "d.c", "s",
    },
}
# fmt: on

# Wikipedia note calls and maintenance tags, removed before splitting.
NOTE_CALLS = re.compile(
    r"\[(?:\d{1,3}|[a-z]|notes? \d{1,3}|réf\. (?:nécessaire|souhaitée)|citation needed"
    r"|Anm\. \d{1,3}|senza fonte|cita requerida)\]",
    re.IGNORECASE,
)

# End marks, possibly followed by closing quotes or brackets, then spaces. The spaces may be
# missing: a text copied from a PDF or from a badly built page often lost them.
BOUNDARY = re.compile(r"[.!?…]+(?:\s?[»”\"’)\]])*(\s*)")

# Separators a paste may carry that Python does not read as spaces, and the soft hyphen.
INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
SOFT_HYPHEN = "\u00ad"

# The title of a division, written in the pasted text: # part, ## chapter, ### section.
HEADING = re.compile(rf"^(#{{1,{MAX_LEVEL}}})\s+(.*)$")

OPENING_MARKS = '«“"‘(¿¡—–-[ '

WORD_BEFORE = re.compile(r"([^\W\d_](?:[^\W\d_]|\.(?=[^\W\d_]))*|\d+)$")


@dataclass(frozen=True)
class Sentence:
    text: str
    starts_paragraph: bool = False
    # 0 for a sentence; 1 to MAX_LEVEL for the title of a part, a chapter or a section.
    level: int = 0


def _ends_sentence(text, boundary, language):
    following = text[boundary.end() :].lstrip(OPENING_MARKS)
    if not following:
        return False
    if not boundary.group(1):
        # No space after the mark: only an upper-case letter ends the sentence, so that a
        # number (2.5) or a shortened reference (p.76) stays in one piece.
        if not following[0].isupper():
            return False
    elif not (following[0].isupper() or following[0].isdigit()):
        return False
    marks = boundary.group()
    if not marks.startswith(".") or marks.startswith(".."):
        return True
    word = WORD_BEFORE.search(text[: boundary.start()])
    if word is None:
        return True
    word = word.group()
    if word.isdigit():
        # German ordinals (am 3. Oktober) and numbered lists.
        return language != "de"
    if len(word) == 1 and word.isupper():
        # An initial, as in J. Dupont.
        return False
    return word.lower() not in ABBREVIATIONS.get(language, set())


def split_paragraph(paragraph, language):
    sentences = []
    start = 0
    for boundary in BOUNDARY.finditer(paragraph):
        if _ends_sentence(paragraph, boundary, language):
            sentences.append(paragraph[start : boundary.start(1)])
            start = boundary.end()
    sentences.append(paragraph[start:])
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def clean_text(text):
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = INVISIBLE.sub(" ", text).replace(SOFT_HYPHEN, "")
    text = NOTE_CALLS.sub("", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(lines)


def _heading(line):
    """The title of a division written on a line, or None."""
    marks = HEADING.match(line)
    if marks is None or not marks.group(2).strip():
        return None
    return Sentence(marks.group(2).strip(), starts_paragraph=True, level=len(marks.group(1)))


def segment(text, language):
    """Sentences of a pasted text; every line break of the text ends a paragraph."""
    sentences = []
    for line in clean_text(text).split("\n"):
        heading = _heading(line)
        if heading is not None:
            sentences.append(heading)
            continue
        for index, sentence in enumerate(split_paragraph(line, language)):
            sentences.append(Sentence(sentence, starts_paragraph=index == 0))
    return sentences


def unsplit_lines(sentences, language):
    """The numbers of the checked lines that still hold several sentences.

    A text pasted straight into the checking step never went through ``segment``: it stays in
    one piece. The page warns about it and offers to split it again.
    """
    return [
        number
        for number, sentence in enumerate(sentences, start=1)
        if not sentence.level and len(split_paragraph(sentence.text, language)) > 1
    ]


def to_lines(sentences):
    """The editable form of a split: one sentence per line, a blank line between paragraphs."""
    lines = []
    for sentence in sentences:
        if (sentence.starts_paragraph or sentence.level) and lines:
            lines.append("")
        if sentence.level:
            lines.append(f"{'#' * sentence.level} {sentence.text}")
        else:
            lines.append(sentence.text)
    return "\n".join(lines)


def from_lines(text):
    """Sentences from their editable form, as checked by the person who adds the text."""
    sentences = []
    new_paragraph = True
    for line in clean_text(text).split("\n"):
        if not line:
            new_paragraph = True
            continue
        heading = _heading(line)
        if heading is not None:
            sentences.append(heading)
            new_paragraph = True
            continue
        sentences.append(Sentence(line, starts_paragraph=new_paragraph))
        new_paragraph = False
    return sentences
