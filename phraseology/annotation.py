"""Annotating the text being read: the entries that words chosen by a reader may attest."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Q

from corpus.models import TokenAnalysis
from corpus.search import default_layer
from corpus.text import normalize

from .schema import format_schema, parse_schema
from .spotting import spot_units, visible_units

SEARCH_RESULTS = 10
# The relation of an object, active or passive, as written in the schema of an entry.
OBJECT = "obj|nsubj:pass"


def suggested_units(user, tokens):
    """Known units whose words are all among the chosen ones, validated units first."""
    text = " ".join(token.form for token in tokens)
    _words, spots = spot_units(text, user, describe=False)
    return [spot.unit for spot in spots]


def search_units(user, query):
    """Units the user may see whose reference form or schema contains the query."""
    query = " ".join(query.split())[:100]
    if not query:
        return []
    units = visible_units(user).filter(
        Q(reference_form__icontains=query) | Q(schema__icontains=normalize(query))
    )
    return list(units.order_by("reference_form", "pk")[:SEARCH_RESULTS])


def _relation(deprel):
    deprel = deprel.lower()
    if deprel == "nsubj:pass" or deprel.split(":")[0] == "obj":
        return OBJECT
    # A relation without subtype covers its subtypes.
    return deprel.split(":")[0]


def guess_schema(tokens, layer=None):
    """A schema from the automatic analysis of the chosen words; "" if they make no tree.

    Every word but one must depend on another chosen word; the one left governs the others.
    """
    layer = layer or default_layer()
    ids = {token.pk for token in tokens}
    if layer is None or len(ids) < 2:
        return ""
    analyses = {
        analysis.token_id: analysis
        for analysis in TokenAnalysis.objects.filter(layer=layer, token_id__in=ids, part=0)
    }
    if set(analyses) != ids or not all(analysis.lemma_norm for analysis in analyses.values()):
        return ""
    children, roots = defaultdict(list), []
    for analysis in analyses.values():
        if analysis.head_id in ids and analysis.head_id != analysis.token_id:
            children[analysis.head_id].append(analysis)
        else:
            roots.append(analysis)
    if len(roots) != 1:
        return ""
    edges, waiting = [], [roots[0]]
    while waiting:
        head = waiting.pop(0)
        for child in sorted(children[head.token_id], key=lambda analysis: analysis.token_id):
            edges.append(f"{head.lemma_norm} -{_relation(child.deprel)}-> {child.lemma_norm}")
            waiting.append(child)
    if len(edges) != len(ids) - 1:
        return ""
    try:
        return format_schema(parse_schema("; ".join(edges)))
    except ValidationError:
        return ""
