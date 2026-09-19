"""Find and replace in the working text of a version, with a preview sentence by sentence.

The text searched is plain text, never a regular expression written by the user."""

import re
import unicodedata

from .diffs import word_diff

LONG_VOWELS = {"a": "ā", "e": "ē", "i": "ī", "o": "ō", "u": "ū", "y": "ȳ"}


def _base(char):
    return unicodedata.normalize("NFD", char)[0]


def build_pattern(find, whole_word=False, match_case=False, ignore_macrons=True):
    """A compiled pattern for plain text ``find``; None when there is nothing to find."""
    find = unicodedata.normalize("NFC", find or "")
    if not find.strip():
        return None
    parts = []
    for char in find:
        base = _base(char)
        if ignore_macrons and base.lower() in LONG_VOWELS:
            short, long = base.lower(), LONG_VOWELS[base.lower()]
            choices = {short, long}
            if not match_case:
                choices |= {short.upper(), long.upper()}
            elif base.isupper():
                choices = {short.upper(), long.upper()}
            parts.append("[" + "".join(sorted(choices)) + "]")
        else:
            parts.append(re.escape(char))
    body = "".join(parts)
    if whole_word:
        body = rf"(?<!\w){body}(?!\w)"
    return re.compile(body, 0 if match_case else re.IGNORECASE)


def preview(rows, pattern, replacement):
    """[{row, count, after, chunks}] of the sentences the replacement changes."""
    changes = []
    if pattern is None:
        return changes
    for row in rows:
        before = row["saved"]
        if not before:
            continue
        after, count = pattern.subn(lambda match: _cased(match, pattern, replacement), before)
        if count and after != before:
            changes.append(
                {"row": row, "count": count, "after": after, "chunks": word_diff(before, after)}
            )
    return changes


def _cased(match, pattern, replacement):
    """The replacement; when case is ignored, a capital found stays a capital."""
    found = match.group(0)
    if pattern.flags & re.IGNORECASE and replacement and found[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement
