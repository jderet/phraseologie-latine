"""The schema of a unit: lemmas linked by syntactic relations (Q11).

A schema is written one relation at a time, the governing lemma first:
``capio -obj-> consilium``. Several relations are separated by ";" and form a tree, as in
``redigo -obl-> memoria; memoria -case-> in``. A relation may have alternatives separated
by "|": ``gero -obj|nsubj:pass-> bellum`` also finds the passive *bellum geritur*. A
relation without subtype also matches its subtypes: ``obl`` matches ``obl:arg``. A query may
leave one dependent open, written ``*``: ``capio -obj-> *`` finds every object of *capio*.
"""

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.utils.translation import gettext, gettext_noop, pgettext_lazy

from corpus.text import normalize

# Universal Dependencies relations; LatinCy writes the root of a sentence ROOT.
RELATIONS = frozenset(
    "acl advcl advmod amod appos aux case cc ccomp clf compound conj cop csubj dep det "
    "discourse dislocated expl fixed flat goeswith iobj list mark nmod nsubj nummod obj obl "
    "orphan parataxis punct reparandum root vocative xcomp".split()
)
# The relations offered when a schema is drawn, the common ones first; each label reads after
# "a pour", as in "capere a pour objet consilium". The root is no relation between two words.
RELATION_CHOICES = (
    ("obj", pgettext_lazy("relation syntaxique", "objet"), True),
    ("nsubj", pgettext_lazy("relation syntaxique", "sujet"), True),
    ("nsubj:pass", pgettext_lazy("relation syntaxique", "sujet d’un passif"), True),
    ("obl", pgettext_lazy("relation syntaxique", "complément circonstanciel"), True),
    ("amod", pgettext_lazy("relation syntaxique", "épithète"), True),
    ("advmod", pgettext_lazy("relation syntaxique", "adverbe"), True),
    ("nmod", pgettext_lazy("relation syntaxique", "complément du nom"), True),
    ("case", pgettext_lazy("relation syntaxique", "préposition"), True),
    ("xcomp", pgettext_lazy("relation syntaxique", "infinitif complément"), True),
    ("iobj", pgettext_lazy("relation syntaxique", "complément d’attribution"), True),
    ("ccomp", pgettext_lazy("relation syntaxique", "complétive"), False),
    ("advcl", pgettext_lazy("relation syntaxique", "subordonnée circonstancielle"), False),
    ("acl", pgettext_lazy("relation syntaxique", "proposition complément du nom"), False),
    ("csubj", pgettext_lazy("relation syntaxique", "proposition sujet"), False),
    ("det", pgettext_lazy("relation syntaxique", "déterminant"), False),
    ("nummod", pgettext_lazy("relation syntaxique", "numéral"), False),
    ("cop", pgettext_lazy("relation syntaxique", "copule"), False),
    ("aux", pgettext_lazy("relation syntaxique", "auxiliaire"), False),
    ("mark", pgettext_lazy("relation syntaxique", "conjonction de subordination"), False),
    ("conj", pgettext_lazy("relation syntaxique", "coordonné"), False),
    ("cc", pgettext_lazy("relation syntaxique", "coordination"), False),
    ("appos", pgettext_lazy("relation syntaxique", "apposition"), False),
    ("vocative", pgettext_lazy("relation syntaxique", "vocatif"), False),
    ("fixed", pgettext_lazy("relation syntaxique", "expression figée"), False),
    ("flat", pgettext_lazy("relation syntaxique", "nom composé"), False),
    ("compound", pgettext_lazy("relation syntaxique", "composé"), False),
    ("parataxis", pgettext_lazy("relation syntaxique", "parataxe"), False),
    ("discourse", pgettext_lazy("relation syntaxique", "particule de discours"), False),
    ("dislocated", pgettext_lazy("relation syntaxique", "élément détaché"), False),
    ("expl", pgettext_lazy("relation syntaxique", "explétif"), False),
    ("orphan", pgettext_lazy("relation syntaxique", "ellipse"), False),
    ("list", pgettext_lazy("relation syntaxique", "liste"), False),
    ("clf", pgettext_lazy("relation syntaxique", "classificateur"), False),
    ("goeswith", pgettext_lazy("relation syntaxique", "fragment de mot"), False),
    ("reparandum", pgettext_lazy("relation syntaxique", "reprise"), False),
    ("punct", pgettext_lazy("relation syntaxique", "ponctuation"), False),
    ("dep", pgettext_lazy("relation syntaxique", "relation indéterminée"), False),
)
MAX_RELATIONS = 4
# An open dependent, in queries only.
SLOT = "*"

EDGE_PATTERN = re.compile(
    r"^(?P<head>[^\W\d_]+)\s*[-—–]\s*(?P<relations>[a-zA-Z:|\s]+?)\s*(?:->|→)\s*"
    r"(?P<dependent>[^\W\d_]+|\*)$"
)


@dataclass(frozen=True)
class Edge:
    head: str
    relations: tuple[str, ...]
    dependent: str

    def __str__(self):
        return f"{self.head} -{'|'.join(self.relations)}-> {self.dependent}"

    @property
    def label(self):
        return f"{self.head} —{'|'.join(self.relations)}→ {self.dependent}"


TREE_MESSAGE = gettext_noop(
    "Les relations doivent former un seul ensemble, à partir d’un seul lemme."
)


def _relations(text):
    relations = []
    for relation in text.split("|"):
        relation = relation.strip().lower()
        if relation.split(":", 1)[0] not in RELATIONS:
            raise ValidationError(
                gettext("Relation syntaxique inconnue : « %(relation)s ».")
                % {"relation": relation},
                code="relation",
            )
        if relation not in relations:
            relations.append(relation)
    return tuple(relations)


def parse_schema(text, slot=False):
    """The relations of a schema, the root's first; raise ValidationError if it is not valid.

    With ``slot``, one dependent may be left open (``*``), as queries allow.
    """
    parts = [part.strip() for part in (text or "").split(";") if part.strip()]
    if len(parts) > MAX_RELATIONS:
        raise ValidationError(
            gettext("Un schéma compte au plus %(limit)d relations.") % {"limit": MAX_RELATIONS},
            code="too_many",
        )
    edges = []
    for part in parts:
        match = EDGE_PATTERN.match(part)
        if match is None:
            raise ValidationError(
                gettext(
                    "Écrivez chaque relation ainsi : capio -obj-> consilium (et non « %(part)s »)."
                )
                % {"part": part},
                code="syntax",
            )
        dependent = match["dependent"]
        if dependent == SLOT and not slot:
            raise ValidationError(
                gettext("La case vide * ne sert qu’à chercher : écrivez un lemme."), code="slot"
            )
        dependent = dependent if dependent == SLOT else normalize(dependent)
        edges.append(Edge(normalize(match["head"]), _relations(match["relations"]), dependent))
    if sum(edge.dependent == SLOT for edge in edges) > 1:
        raise ValidationError(gettext("Un schéma n’a qu’une case vide."), code="two_slots")
    return _as_tree(edges)


def _as_tree(edges):
    if not edges:
        return []
    dependents = [edge.dependent for edge in edges]
    if len(set(dependents)) != len(dependents):
        raise ValidationError(
            gettext("Chaque lemme ne dépend que d’un seul autre."), code="two_heads"
        )
    heads = {edge.head for edge in edges}
    roots = heads - set(dependents)
    if len(roots) != 1:
        raise ValidationError(gettext(TREE_MESSAGE), code="tree")
    root = roots.pop()
    ordered, reached = [], {root}
    while len(ordered) < len(edges):
        following = [e for e in edges if e.head in reached and e.dependent not in reached]
        if not following:
            raise ValidationError(gettext(TREE_MESSAGE), code="tree")
        for edge in following:
            ordered.append(edge)
            reached.add(edge.dependent)
    return ordered


def format_schema(edges):
    """The schema as stored: one line, the relations separated by "; "."""
    return "; ".join(str(edge) for edge in edges)


def schema_lemmas(edges):
    """The lemmas of a schema, the root first."""
    lemmas = []
    for edge in edges:
        for lemma in (edge.head, edge.dependent):
            if lemma not in lemmas:
                lemmas.append(lemma)
    return lemmas
