"""What the editor shows around the sentences: the tabs of its side panel, the menus of its
toolbar, and what each row carries for the filters and badges."""

import unicodedata
from dataclasses import dataclass

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# The fragment of a tab is loaded for the active sentence: its address carries this mark.
SEGMENT_MARK = "{segment}"


@dataclass(frozen=True)
class PanelTab:
    name: str
    label: str
    hint: str = ""
    fragment_url: str = ""


def _fragment(name, version):
    """The address of a tab fragment for any sentence, with the sentence as a mark."""
    return reverse(name, args=[version.pk, 0]).replace("/0/", f"/{SEGMENT_MARK}/")


def panel_tabs(version):
    """The tabs of the side panel, in order; the first is open by default."""
    return [
        PanelTab("justifications", _("Justifications")),
        PanelTab("corpus", _("Corpus")),
    ]


# The status of a sentence with no Latin yet.
TODO = "todo"
STATUS_ORDER = [TODO, "draft", "translated", "reviewed"]


def row_status(row):
    sentence = row["sentence"]
    if not row["saved"]:
        return TODO
    return getattr(sentence, "status", None) or "draft"


def row_data(row):
    """Data attributes of a row, read by the filters and badges of the editor."""
    return {
        "status": row_status(row),
        "source-changed": "1" if row["source_changed"] else "0",
    }


def status_counts(rows):
    """[(status, label, count, percent)] of the rows, for the bar of progress."""
    labels = {
        TODO: _("à traduire"),
        "draft": _("brouillon"),
        "translated": _("traduite"),
        "reviewed": _("relue"),
    }
    total = len(rows) or 1
    counts = dict.fromkeys(STATUS_ORDER, 0)
    for row in rows:
        counts[row["data"]["status"]] += 1
    items, offset = [], 0.0
    for status in STATUS_ORDER:
        share = counts[status] * 100 / total
        items.append(
            {
                "status": status,
                "label": labels[status],
                "count": counts[status],
                "x": f"{offset:.3f}",
                "width": f"{share:.3f}",
            }
        )
        offset += share
    return items


# Filters of the sentences: name in the address, label, test on a row.
FILTERS = {
    "a-traduire": (_("à traduire"), lambda row: row["data"]["status"] == TODO),
    "brouillons": (_("brouillons"), lambda row: row["data"]["status"] == "draft"),
    "non-relues": (
        _("traduites mais pas relues"),
        lambda row: row["data"]["status"] in ("draft", "translated"),
    ),
    "source-modifiee": (
        _("texte source modifié"),
        lambda row: row["data"]["source-changed"] == "1",
    ),
}


def fold(text):
    """Text compared by the search of the editor: no accents, macrons or case."""
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def filter_rows(rows, name, query):
    """The rows a filter and a search keep; the numbers of the sentences do not change."""
    test = FILTERS.get(name, (None, None))[1]
    needle = fold(query).strip()
    kept = []
    for row in rows:
        if test is not None and not test(row):
            continue
        if needle and needle not in fold(row["segment"].text) and needle not in fold(row["text"]):
            continue
        kept.append(row)
    return kept


def filter_choices():
    return [(name, label) for name, (label, _test) in FILTERS.items()]
