"""Latin text: search normalization and tokenization.

The printed form of the edition is always kept; the normalized form only serves search,
so that "Vīuō", "vivo" and "VIVO" are found together.
"""

import re
import unicodedata
from dataclasses import dataclass

LIGATURES = str.maketrans({"æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe"})

# A word: letters or digits of any script, possibly with combining marks that have no
# precomposed form. Some Perseus editions write Greek in Beta code (*dio/dwron, a)reth/):
# its accent signs stay inside the word, and so do breathings followed by a letter.
WORD_PATTERN = re.compile(
    r"(?:\*[()\\/=|+]*(?=[^\W_]))?[^\W_](?:[^\W_]|[̀-ͯ]|[()](?=[^\W_])|[\\/=|+])*"
)

# Marks that open a quotation or a parenthesis and belong to the following word.
OPENING_MARKS = set("([{«‹„“‘¿¡<⟨")

# Greek script, or the signs of Beta code inside a word.
FOREIGN_PATTERN = re.compile(r"[Ͱ-Ͽἀ-῿]|^\*|[()\\/=|+]")


@dataclass(frozen=True, slots=True)
class TextToken:
    form: str
    # Opening marks just before the word.
    before: str = ""
    # Punctuation and spaces after the word, up to the next word.
    after: str = ""
    # Written in another script than Latin (Greek quotations).
    is_foreign: bool = False


def normalize_space(text):
    """Compose Unicode characters and reduce every run of spaces to one space."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def normalize(form):
    """Search form of a word: no macrons or diacritics, lower case, u for v, i for j.

    Ligatures are expanded (æ becomes ae, œ becomes oe).
    """
    decomposed = unicodedata.normalize("NFD", form.translate(LIGATURES))
    bare = "".join(char for char in decomposed if not unicodedata.combining(char))
    return bare.lower().replace("v", "u").replace("j", "i")


def _split_gap(gap):
    """Share the characters between two words: (after the previous, before the next)."""
    last_space = max(gap.rfind(" "), gap.rfind("\n"))
    if last_space >= 0:
        return gap[: last_space + 1], gap[last_space + 1 :]
    if gap and all(char in OPENING_MARKS for char in gap):
        return "", gap
    return gap, ""


def tokenize(text):
    """Split a text into words, keeping the punctuation and spaces around each word.

    Joining ``before + form + after`` of every token gives the text back exactly.
    """
    text = unicodedata.normalize("NFC", text)
    matches = list(WORD_PATTERN.finditer(text))
    tokens = []
    for index, match in enumerate(matches):
        if index == 0:
            before = text[: match.start()]
        else:
            before = _split_gap(text[matches[index - 1].end() : match.start()])[1]
        if index == len(matches) - 1:
            after = text[match.end() :]
        else:
            after = _split_gap(text[match.end() : matches[index + 1].start()])[0]
        form = match.group()
        tokens.append(TextToken(form, before, after, bool(FOREIGN_PATTERN.search(form))))
    return tokens
