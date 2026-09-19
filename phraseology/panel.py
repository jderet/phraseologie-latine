"""What a word of a text is, for the reader who points at it: its units and its analysis."""

from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _

from accounts.roles import is_reviewer
from corpus.models import Author, TokenAnalysis
from corpus.search import default_layer

from .abstract import PARTS_OF_SPEECH
from .models import Attestation, Equivalent, UnitFrequency
from .permissions import can_edit_unit
from .reading import shown_status
from .services import is_current
from .spotting import unit_attestations, visible_units

EXAMPLES_SHOWN = 3
AUTHORS_SHOWN = 6

# Universal Dependencies relations, as the reader reads them.
RELATIONS = {
    "acl": _("proposition complément du nom"),
    "advcl": _("subordonnée circonstancielle"),
    "advmod": _("adverbe"),
    "amod": _("adjectif épithète"),
    "appos": _("apposition"),
    "aux": _("auxiliaire"),
    "case": _("préposition"),
    "cc": _("coordination"),
    "ccomp": _("complétive"),
    "conj": _("élément coordonné"),
    "cop": _("copule"),
    "csubj": _("sujet propositionnel"),
    "det": _("déterminant"),
    "fixed": _("locution"),
    "flat": _("nom composé"),
    "iobj": _("objet second"),
    "mark": _("subordonnant"),
    "nmod": _("complément du nom"),
    "nsubj": _("sujet"),
    "nummod": _("numéral"),
    "obj": _("objet"),
    "obl": _("complément du verbe"),
    "parataxis": _("parataxe"),
    "punct": _("ponctuation"),
    "root": _("racine de la phrase"),
    "vocative": _("vocatif"),
    "xcomp": _("attribut ou infinitif complément"),
}


def word_attestations(user, token):
    """Attestations the user may see that cover a word; rejected ones are left out."""
    return (
        Attestation.objects.active()
        .filter(tokens=token, is_hidden=False, unit__in=visible_units(user))
        .exclude(status=Attestation.Status.REJECTED)
        .select_related("unit", "created_by", "reviewed_by", "sense", "realization")
        .order_by("unit__reference_form", "pk")
    )


def other_examples(attestation, author_id, limit=EXAMPLES_SHOWN):
    """A few other attestations of the unit, examples first, from other authors first."""
    others = [
        item for item in unit_attestations(attestation.unit, limit + 6) if item.pk != attestation.pk
    ]
    authors = dict(
        Attestation.objects.filter(pk__in=[item.pk for item in others]).values_list(
            "pk", "passage__edition__work__author_id"
        )
    )
    others.sort(key=lambda item: authors.get(item.pk) == author_id)
    return others[:limit]


def unit_card(user, attestation, token):
    """What the panel shows of a unit a word belongs to."""
    unit = attestation.unit
    senses = unit.senses.active().filter(is_hidden=False)
    equivalents = Equivalent.objects.active().filter(is_hidden=False)
    frequency = UnitFrequency.objects.filter(unit=unit).first()
    authors = []
    if frequency is not None:
        found = Author.objects.in_bulk([row[0] for row in frequency.by_author])
        rows = sorted(frequency.by_author, key=lambda row: -row[1])[:AUTHORS_SHOWN]
        authors = [(found[pk], total) for pk, total, _core in rows if pk in found]
    return {
        "attestation": attestation,
        "unit": unit,
        "status": shown_status(attestation),
        "senses": list(senses.prefetch_related(Prefetch("equivalents", queryset=equivalents))),
        "frequency": frequency,
        "frequency_is_current": is_current(frequency, unit),
        "authors": authors,
        "examples": other_examples(attestation, token.passage.edition.work.author_id),
        "can_review": is_reviewer(user),
        # Outside the core, an attestation found automatically is never validated (T2).
        "can_validate": attestation.status != Attestation.Status.VALIDATED
        and (
            attestation.level != Attestation.Level.AUTOMATIC or token.passage.edition.work.is_core
        ),
        "can_edit": can_edit_unit(user, unit),
    }


def word_analysis(token):
    """The analysis of a word in the default layer, part by part; None without a layer."""
    layer = default_layer()
    if layer is None:
        return None
    parts = []
    analyses = TokenAnalysis.objects.filter(layer=layer, token=token).select_related("head")
    for analysis in analyses.order_by("part"):
        relation = analysis.deprel.split(":")[0].lower()
        parts.append(
            {
                "analysis": analysis,
                "part_of_speech": PARTS_OF_SPEECH.get(analysis.upos, analysis.upos),
                "features": [feature for feature in analysis.feats.split("|") if feature],
                "relation": RELATIONS.get(relation, ""),
            }
        )
    return {"layer": layer, "parts": parts}
