"""Splitting a source text into sentences.

The split is only a proposal: the person who adds a text checks it, one sentence per line,
before saving. A line break always ends a sentence; a blank line starts a new paragraph.
"""

import re
import unicodedata
from dataclasses import dataclass

MAX_SENTENCES = 500
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

# End marks, possibly followed by closing quotes or brackets, then spaces.
BOUNDARY = re.compile(r"[.!?…]+(?:\s?[»”\"’)\]])*(\s+)")

OPENING_MARKS = '«“"‘(¿¡—–-[ '

WORD_BEFORE = re.compile(r"([^\W\d_](?:[^\W\d_]|\.(?=[^\W\d_]))*|\d+)$")


@dataclass(frozen=True)
class Sentence:
    text: str
    starts_paragraph: bool = False


def _ends_sentence(text, boundary, language):
    following = text[boundary.end() :].lstrip(OPENING_MARKS)
    if not following or not (following[0].isupper() or following[0].isdigit()):
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
    text = NOTE_CALLS.sub("", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(lines)


def segment(text, language):
    """Sentences of a pasted text; every line break of the text ends a paragraph."""
    sentences = []
    for line in clean_text(text).split("\n"):
        for index, sentence in enumerate(split_paragraph(line, language)):
            sentences.append(Sentence(sentence, starts_paragraph=index == 0))
    return sentences


def to_lines(sentences):
    """The editable form of a split: one sentence per line, a blank line between paragraphs."""
    lines = []
    for sentence in sentences:
        if sentence.starts_paragraph and lines:
            lines.append("")
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
        sentences.append(Sentence(line, starts_paragraph=new_paragraph))
        new_paragraph = False
    return sentences
