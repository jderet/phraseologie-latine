"""Quality checks of a working text, as in translation software.

Only the form is checked: punctuation, numbers, brackets, spaces, the macrons of a word from
one sentence to another, the glossary of the project, justifications to review. The corpus is
never consulted: no alert says that a combination is not attested (Q47).
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

from .glossary import find_terms, fold, latin_present

IDENTICAL = "identical"
END = "end"
NUMBERS = "numbers"
BRACKETS = "brackets"
SPACES = "spaces"
MACRONS = "macrons"
GLOSSARY = "glossary"
JUSTIFICATION = "justification"
SOURCE_CHANGED = "source"
LENGTH = "length"

LABELS = {
    IDENTICAL: _("latin identique à la phrase source"),
    END: _("ponctuation finale différente"),
    NUMBERS: _("nombres différents"),
    BRACKETS: _("parenthèse ou guillemet non refermé"),
    SPACES: _("espace avant une ponctuation"),
    MACRONS: _("même mot écrit avec et sans macrons"),
    GLOSSARY: _("terme du glossaire absent"),
    JUSTIFICATION: _("justification à revoir"),
    SOURCE_CHANGED: _("texte source modifié depuis la dernière étape"),
    LENGTH: _("longueur inhabituelle"),
}

PAIRS = [("(", ")"), ("[", "]"), ("«", "»"), ("“", "”")]
DIGITS = re.compile(r"\d+")
WORD = re.compile(r"[^\W\d_]+")
SPACE_BEFORE = re.compile(r"\s[,.;:!?]")
FINAL = re.compile(r"[?!]")


@dataclass(frozen=True)
class Alert:
    code: str
    detail: str = ""

    @property
    def label(self):
        return LABELS[self.code]


def fingerprint(text):
    """Short hash of a Latin sentence: an ignored alert comes back when the Latin changes."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _final_mark(text):
    text = text.rstrip(" »”\"')]")
    return text[-1] if text and FINAL.match(text[-1]) else ""


def check_sentence(source, latin):
    """Alerts on one sentence that do not depend on the others."""
    alerts = []
    if fold(latin).strip() == fold(source).strip():
        alerts.append(Alert(IDENTICAL))
    if _final_mark(source) != _final_mark(latin):
        alerts.append(
            Alert(END, f"« {_final_mark(source) or '.'} » / « {_final_mark(latin) or '.'} »")
        )
    latin_numbers = DIGITS.findall(latin)
    if latin_numbers and sorted(latin_numbers) != sorted(DIGITS.findall(source)):
        alerts.append(Alert(NUMBERS, " ".join(latin_numbers)))
    for opening, closing in PAIRS:
        if latin.count(opening) != latin.count(closing):
            alerts.append(Alert(BRACKETS, f"{opening}{closing}"))
            break
    else:
        if latin.count('"') % 2:
            alerts.append(Alert(BRACKETS, '"'))
    if SPACE_BEFORE.search(latin):
        alerts.append(Alert(SPACES))
    source_words, latin_words = len(source.split()), len(latin.split())
    if source_words >= 4 and (latin_words < source_words / 4 or latin_words > source_words * 3):
        alerts.append(Alert(LENGTH, f"{latin_words} / {source_words}"))
    return alerts


def macron_variants(texts):
    """{folded word: set of spellings} for words written with different macrons."""
    spellings = defaultdict(set)
    for text in texts:
        for word in WORD.findall(text):
            spellings[fold(word)].add(word.lower())
    return {key: forms for key, forms in spellings.items() if len(forms) > 1}


def check_rows(rows, terms=(), ignored=()):
    """{segment id: [Alert]} for the rows of the editor that have Latin.

    ``terms`` are the adopted terms of the glossary; ``ignored`` a set of (segment id, code,
    fingerprint) the writers chose to ignore.
    """
    translated = [row for row in rows if row["saved"]]
    variants = macron_variants(row["saved"] for row in translated)
    found = {}
    for row in translated:
        source, latin = row["segment"].text, row["saved"]
        alerts = check_sentence(source, latin)
        mixed = sorted(
            {
                "/".join(sorted(variants[fold(word)]))
                for word in WORD.findall(latin)
                if fold(word) in variants
            }
        )
        if mixed:
            alerts.append(Alert(MACRONS, ", ".join(mixed)))
        for item in find_terms(source, terms):
            if not latin_present(latin, item.entry):
                alerts.append(
                    Alert(GLOSSARY, f"{item.entry.source_term} → {item.entry.latin_term}")
                )
        if any(justification.needs_review for justification in row.get("justifications", [])):
            alerts.append(Alert(JUSTIFICATION))
        if row.get("source_changed"):
            alerts.append(Alert(SOURCE_CHANGED))
        stamp = fingerprint(latin)
        alerts = [
            alert for alert in alerts if (row["segment"].pk, alert.code, stamp) not in ignored
        ]
        if alerts:
            found[row["segment"].pk] = alerts
    return found


def ignored_alerts(version):
    return set(version.ignored_alerts.values_list("segment_id", "code", "fingerprint"))
