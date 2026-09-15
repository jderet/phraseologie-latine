"""Differences between two Latin sentences, word by word."""

import difflib
import re
from dataclasses import dataclass

SAME, ADDED, REMOVED = "same", "added", "removed"

# Words, runs of spaces and punctuation marks, so that the pieces join back into the text.
TOKENS = re.compile(r"\w+|\s+|[^\w\s]")


@dataclass(frozen=True)
class Chunk:
    kind: str
    text: str


def word_diff(before, after):
    """The pieces of text kept, removed and added from ``before`` to ``after``."""
    old, new = TOKENS.findall(before), TOKENS.findall(after)
    chunks = []
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            _append(chunks, SAME, old[old_start:old_end])
            continue
        _append(chunks, REMOVED, old[old_start:old_end])
        _append(chunks, ADDED, new[new_start:new_end])
    return chunks


def _append(chunks, kind, tokens):
    text = "".join(tokens)
    if not text:
        return
    if chunks and chunks[-1].kind == kind:
        chunks[-1] = Chunk(kind, chunks[-1].text + text)
    else:
        chunks.append(Chunk(kind, text))
