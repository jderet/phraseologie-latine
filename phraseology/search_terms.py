"""Constructions looked for in a corpus search: the occurrences of the schema of a unit.

A search for attestations of *rem pūblicam administrāre* looks for the construction *rēs pūblica*,
found wherever the analysis links its lemmas as its schema does, and for *administro* nearby.
The occurrences are found automatically, from the analysis of the corpus.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models import Q

from corpus.forms import MAX_CONSTRUCTIONS, MODE_FORM, MODE_LEMMA, TERM_NUMBERS
from corpus.search import NoAnalysisLayer, default_layer

from .frequency import occurrence_words, schema_matches
from .markup import STATUS_ORDER, resolve, segments, units_named
from .schema import parse_schema, schema_lemmas
from .schema_help import WORD, lemma_choices
from .spotting import visible_units


@dataclass(frozen=True, eq=False)
class ConstructionTerm:
    """A unit looked for by its schema; the governing word of an occurrence stands for it."""

    unit: object
    edges: tuple
    # A construction is found in the analysis, like a lemma.
    lemma = True

    def __bool__(self):
        return bool(self.edges)

    def condition(self, layer):
        """The words that govern an occurrence of the schema."""
        if layer is None:
            raise NoAnalysisLayer("A construction search needs an analysis layer.")
        return Q(pk__in=schema_matches(list(self.edges), layer).values("token_id"))

    def occurrences(self, token_ids, layer):
        """For each governing word among ``token_ids``, the words of its occurrence."""
        roots = list(
            schema_matches(list(self.edges), layer)
            .filter(token_id__in=token_ids)
            .values_list("token_id", "part", "token__position")
        )
        words = occurrence_words(roots, list(self.edges), layer)
        return {root[0]: set(ids) for root, ids in zip(roots, words, strict=True)}


def construction_term(unit):
    try:
        edges = parse_schema(unit.schema)
    except ValidationError:
        edges = []
    return ConstructionTerm(unit, tuple(edges))


def construction_units(user, pks):
    """The units the user may see among ``pks`` that have a schema, in the order given."""
    units = visible_units(user).exclude(schema="").in_bulk(list(pks))
    return [units[pk] for pk in dict.fromkeys(pks) if pk in units]


def construction_named(user, name):
    """The unit a name most likely means, validated first; None if no unit with a schema has it."""
    units = [unit for unit in units_named(user, name) if unit.schema]
    units.sort(key=lambda unit: (STATUS_ORDER.get(unit.status, len(STATUS_ORDER)), unit.pk))
    return units[0] if units else None


def form_words(marked):
    """The words of a reference form outside its marks and abstract words, in order, as they
    are written."""
    return [
        word
        for part in segments(marked or "")
        if not part.name and not part.abstract
        for word in WORD.findall(part.text)
    ]


def marked_search(user, marked, schema=""):
    """The first search for attestations of a unit: the units its reference form marks, as
    constructions, then its other words.

    Each word is looked for by its lemma, the one of the schema if it has several, or as it is
    written when the analysis of the corpus does not know it.
    """
    try:
        edges = parse_schema(schema)
    except ValidationError:
        edges = []
    units = [part.unit for part in resolve(user, marked or "", edges) if part.unit is not None]
    units = [unit for unit in dict.fromkeys(units) if construction_term(unit)][:MAX_CONSTRUCTIONS]
    layer = default_layer()
    lemmas_of_schema = set(schema_lemmas(edges))
    terms = []
    for word in form_words(marked):
        choice = lemma_choices(word, layer)
        if choice["known"]:
            lemmas = [lemma for lemma in choice["lemmas"] if lemma in lemmas_of_schema]
            term = ((lemmas or choice["lemmas"])[0], MODE_LEMMA)
        else:
            term = (word, MODE_FORM)
        if term not in terms:
            terms.append(term)
    initial = {}
    for number, (value, mode) in zip(TERM_NUMBERS, terms, strict=False):
        initial[f"term{number}"] = value
        initial[f"mode{number}"] = mode
    if units:
        initial["construction"] = [unit.pk for unit in units]
    return initial
