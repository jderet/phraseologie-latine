"""The schema of a unit: lemmas linked by syntactic relations (Q11).

A schema is written one relation at a time, the governing lemma first:
``capio -obj-> consilium``. Several relations are separated by ";" and form a tree. A relation
may have alternatives separated by "|": ``gero -obj|nsubj:pass-> bellum`` also finds the passive
*bellum geritur*. A relation without subtype also matches its subtypes: ``obl`` matches
``obl:arg``. A relation written between parentheses is optional: in
``gero -obj-> bellum; gero -(sp)-> cum; cum -reg-> aliquis`` the phrase *cum aliquo* may be
missing; when it is there, its preposition has its regime. A query may leave one dependent
open, written ``*``: ``capio -obj-> *`` finds every object of *capio*.

A prepositional phrase is written with the preposition first, unlike Universal Dependencies:
``redigo -sp-> in; in -reg-> memoria``; the case of the regime may be given, as in
``in -reg:acc-> memoria``. The phrase written as the analysis gives it,
``redigo -obl-> memoria; memoria -case-> in``, is read the same way.
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
# The prepositional phrase, a relation of the project: from its head to the preposition, then
# from the preposition to its regime, whose case may be given as a subtype.
PHRASE = "sp"
REGIME = "reg"
REGIME_CASES = {"acc": "Acc", "abl": "Abl"}
# The relations of the analysis by which the noun of a prepositional phrase depends on its head.
PHRASE_RELATIONS = ("obl", "nmod")
# The relation of the analysis from a noun to its preposition.
CASE = "case"
# The relations offered when a schema is drawn, the common ones first; each label reads after
# "a pour", as in "capere a pour objet consilium". The root is no relation between two words.
RELATION_CHOICES = (
    ("obj", pgettext_lazy("relation syntaxique", "objet"), True),
    ("nsubj", pgettext_lazy("relation syntaxique", "sujet"), True),
    ("nsubj:pass", pgettext_lazy("relation syntaxique", "sujet d’un passif"), True),
    ("sp", pgettext_lazy("relation syntaxique", "syntagme prépositionnel"), True),
    ("reg", pgettext_lazy("relation syntaxique", "régime"), True),
    ("obl", pgettext_lazy("relation syntaxique", "complément circonstanciel"), True),
    ("amod", pgettext_lazy("relation syntaxique", "épithète"), True),
    ("advmod", pgettext_lazy("relation syntaxique", "adverbe"), True),
    ("nmod", pgettext_lazy("relation syntaxique", "complément du nom"), True),
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
# The cases a regime may be given when a schema is drawn.
CASE_CHOICES = (
    ("acc", pgettext_lazy("cas", "accusatif")),
    ("abl", pgettext_lazy("cas", "ablatif")),
)
MAX_RELATIONS = 4
# An open dependent, in queries only.
SLOT = "*"

EDGE_PATTERN = re.compile(
    r"^(?P<head>[^\W\d_]+)\s*[-—–]\s*"
    r"(?:\(\s*(?P<optional>[a-zA-Z:|\s]+?)\s*\)|(?P<relations>[a-zA-Z:|\s]+?))"
    r"\s*(?:->|→)\s*(?P<dependent>[^\W\d_]+|\*)$"
)


def base(relation):
    """A relation without its subtype: obl for obl:arg."""
    return relation.split(":", 1)[0]


@dataclass(frozen=True)
class Edge:
    head: str
    relations: tuple[str, ...]
    dependent: str
    # The expression exists without this relation and what depends on it.
    optional: bool = False

    @property
    def written_relations(self):
        relations = "|".join(self.relations)
        return f"({relations})" if self.optional else relations

    def __str__(self):
        return f"{self.head} -{self.written_relations}-> {self.dependent}"

    @property
    def label(self):
        return f"{self.head} —{self.written_relations}→ {self.dependent}"

    @property
    def kind(self):
        """PHRASE or REGIME for the relations of a prepositional phrase, "" for the others."""
        first = base(self.relations[0])
        return first if first in (PHRASE, REGIME) else ""


TREE_MESSAGE = gettext_noop(
    "Les relations doivent former un seul ensemble, à partir d’un seul lemme."
)


def _relations(text):
    relations = []
    for relation in text.split("|"):
        relation = relation.strip().lower()
        kind, _colon, subtype = relation.partition(":")
        if kind not in RELATIONS | {PHRASE, REGIME}:
            raise ValidationError(
                gettext("Relation syntaxique inconnue : « %(relation)s ».")
                % {"relation": relation},
                code="relation",
            )
        if (kind == PHRASE and subtype) or (kind == REGIME and subtype not in {"", *REGIME_CASES}):
            raise ValidationError(
                gettext(
                    "Relation inconnue : « %(relation)s ». Le régime prend un cas, reg:acc ou "
                    "reg:abl ; le syntagme prépositionnel s’écrit sp."
                )
                % {"relation": relation},
                code="relation",
            )
        if relation not in relations:
            relations.append(relation)
    if len(relations) > 1 and {base(relation) for relation in relations} & {PHRASE, REGIME}:
        raise ValidationError(
            gettext("Le syntagme prépositionnel et le régime ne prennent pas de variante."),
            code="phrase_variant",
        )
    return tuple(relations)


def parse_schema(text, slot=False):
    """The relations of a schema, the root's first; raise ValidationError if it is not valid.

    With ``slot``, one dependent may be left open (``*``), as queries allow. A prepositional
    phrase written as the analysis gives it is rewritten with the preposition first.
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
        optional = match["optional"] is not None
        relations = _relations(match["optional"] if optional else match["relations"])
        edges.append(Edge(normalize(match["head"]), relations, dependent, optional))
    if sum(edge.dependent == SLOT for edge in edges) > 1:
        raise ValidationError(gettext("Un schéma n’a qu’une case vide."), code="two_slots")
    edges = _as_tree(_from_analysis(edges))
    _check_phrases(edges)
    _check_optional(edges)
    return edges


def _from_analysis(edges):
    """Prepositional phrases written as the analysis gives them, with the preposition first.

    ``redigo -obl-> memoria; memoria -case-> in`` becomes ``redigo -sp-> in; in -reg-> memoria``,
    when the noun depends on its head by obl or nmod and has one preposition, which governs
    nothing; ``memoria -case-> in`` alone becomes ``in -reg-> memoria``. Other relations stay.
    """
    rewritten = list(edges)
    for mark in edges:
        if mark.relations != (CASE,):
            continue
        noun, preposition = mark.head, mark.dependent
        marks = [edge for edge in edges if edge.head == noun and edge.relations == (CASE,)]
        heads = [edge for edge in edges if edge.dependent == noun]
        if (
            len(marks) > 1
            or len(heads) > 1
            or any(edge.head == preposition for edge in edges)
            or any(base(r) not in PHRASE_RELATIONS for head in heads for r in head.relations)
        ):
            continue
        rewritten.remove(mark)
        rewritten.append(Edge(preposition, (REGIME,), noun, mark.optional))
        if heads:
            place = rewritten.index(heads[0])
            rewritten[place] = Edge(heads[0].head, (PHRASE,), preposition, heads[0].optional)
    return rewritten


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


def _check_phrases(edges):
    """A preposition has one regime and nothing else; only a preposition has a regime."""
    governed = {edge.dependent: edge for edge in edges}
    for edge in edges:
        if edge.kind == PHRASE:
            children = [child for child in edges if child.head == edge.dependent]
            if len(children) != 1 or children[0].kind != REGIME:
                raise ValidationError(
                    gettext(
                        "La préposition « %(preposition)s » attend son seul régime : "
                        "%(preposition)s -reg-> …"
                    )
                    % {"preposition": edge.dependent},
                    code="no_regime",
                )
        elif edge.kind == REGIME:
            above = governed.get(edge.head)
            if above is not None and above.kind != PHRASE:
                raise ValidationError(
                    gettext(
                        "Seule une préposition a un régime : reliez d’abord « %(preposition)s » "
                        "au mot qui régit le syntagme prépositionnel (sp)."
                    )
                    % {"preposition": edge.head},
                    code="regime",
                )
            if any(child.head == edge.head and child is not edge for child in edges):
                raise ValidationError(
                    gettext("La préposition « %(preposition)s » n’a que son régime.")
                    % {"preposition": edge.head},
                    code="regime",
                )


def _check_optional(edges):
    """A schema keeps one required relation; a phrase, not its regime, is marked optional."""
    if edges and not required_edges(edges):
        raise ValidationError(
            gettext("Une relation au moins est obligatoire : ôtez une paire de parenthèses."),
            code="all_optional",
        )
    for edge in edges:
        if edge.optional and edge.kind == REGIME:
            raise ValidationError(
                gettext(
                    "Le régime suit sa préposition : c’est le syntagme prépositionnel qui se "
                    "marque facultatif, -(sp)->."
                ),
                code="optional_regime",
            )


def required_edges(edges):
    """The relations every occurrence has: not optional, nor under an optional relation."""
    dropped, required = set(), []
    for edge in edges:
        if edge.optional or edge.head in dropped:
            dropped.add(edge.dependent)
        else:
            required.append(edge)
    return required


def corpus_edges(edges):
    """The schema as the analysis writes it: (relations from the root, {lemma: case}).

    The noun of a prepositional phrase depends on the head of the phrase by obl or nmod, and
    governs its preposition: ``mereor -sp-> de; de -reg:abl-> res`` is looked for as
    ``mereor -obl|nmod-> res; res -case-> de``, *res* in the ablative. Relations already
    written as the analysis writes them are kept.
    """
    regimes = {edge.head: edge.dependent for edge in edges if edge.kind == REGIME}
    written, cases = [], {}
    for edge in edges:
        if edge.kind == PHRASE:
            written.append(
                Edge(edge.head, PHRASE_RELATIONS, regimes[edge.dependent], edge.optional)
            )
        elif edge.kind == REGIME:
            written.append(Edge(edge.dependent, (CASE,), edge.head))
            subtype = edge.relations[0].partition(":")[2]
            if subtype:
                cases[edge.dependent] = REGIME_CASES[subtype]
        else:
            written.append(edge)
    return _as_tree(written), cases


def writes_case(text):
    """Whether a written schema links a noun to its preposition as the analysis does (case)."""
    return re.search(r"\bcase\b", text or "", re.IGNORECASE) is not None


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
