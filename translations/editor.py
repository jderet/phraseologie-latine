"""What the editor shows around the sentences: the tabs of its side panel, the menus of its
toolbar, and what each row carries for the filters and badges."""

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


def row_data(row):
    """Data attributes of a row, read by the filters of the editor."""
    return {"source-changed": "1" if row["source_changed"] else "0"}
