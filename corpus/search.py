"""Searching the corpus by word form or lemma, with filters and context.

A query has one to three terms. Each term is one or more patterns separated by "|"; a
pattern ending with "*" matches the beginning of a word. Forms are compared in their
normalized spelling (corpus.text.normalize); lemmas come from the default analysis layer.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q

from .models import AnalysisLayer, Author, Edition, Token, TokenAnalysis
from .text import normalize

CONTEXT_WORDS = 8


class NoAnalysisLayer(ValueError):
    pass


@dataclass(frozen=True)
class Term:
    patterns: tuple[str, ...]
    lemma: bool = False

    def __bool__(self):
        return bool(self.patterns)

    @property
    def rules(self):
        return [
            (normalize(pattern.rstrip("*")), pattern.endswith("*")) for pattern in self.patterns
        ]

    def matches(self, value):
        return any(
            value.startswith(rule) if is_prefix else value == rule for rule, is_prefix in self.rules
        )


def parse_term(text, lemma=False):
    """A term from what was typed: "cap* | cep*" gives the patterns ("cap*", "cep*")."""
    patterns = tuple(part.strip() for part in (text or "").split("|") if part.strip().rstrip("*"))
    return Term(patterns, lemma)


def default_layer():
    return AnalysisLayer.objects.filter(is_default=True).first()


def _patterns(term, field):
    condition = Q(pk__in=[])
    for value, is_prefix in term.rules:
        condition |= Q(**{f"{field}__startswith": value}) if is_prefix else Q(**{field: value})
    return condition


def _condition(term, layer):
    if not term.lemma:
        return _patterns(term, "norm")
    if layer is None:
        raise NoAnalysisLayer("Lemma search needs an analysis layer.")
    analyses = TokenAnalysis.objects.filter(token=OuterRef("pk"), layer=layer)
    return Exists(analyses.filter(_patterns(term, "lemma_norm")))


def _apply_filters(tokens, filters):
    work = "edition__work__"
    if filters.get("core_only"):
        tokens = tokens.filter(**{f"{work}is_core": True})
    lookups = {
        "authors": f"{work}author__in",
        "works": "edition__work__in",
        "text_forms": f"{work}form__in",
        "genres": f"{work}genre__in",
        "registers": f"{work}register__in",
        "periods": f"{work}author__period__in",
    }
    for key, lookup in lookups.items():
        if filters.get(key):
            tokens = tokens.filter(**{lookup: filters[key]})
    if filters.get("date_from") is not None:
        tokens = tokens.filter(**{f"{work}date_to__gte": filters["date_from"]})
    if filters.get("date_to") is not None:
        tokens = tokens.filter(**{f"{work}date_from__lte": filters["date_to"]})
    return tokens


def search_tokens(terms, distance=5, ordered=False, filters=None, layer=None):
    """Words matching the first term that have the other terms within ``distance`` words.

    With ``ordered``, the other terms must come after the first one.
    """
    if layer is None and any(term.lemma for term in terms):
        layer = default_layer()
    first, *others = terms
    hits = Token.objects.filter(edition__is_current=True).filter(_condition(first, layer))
    hits = _apply_filters(hits, filters or {})
    for other in others:
        lowest = 1 if ordered else -distance
        neighbours = (
            Token.objects.filter(
                edition=OuterRef("edition"),
                position__gte=OuterRef("position") + lowest,
                position__lte=OuterRef("position") + distance,
            )
            .exclude(position=OuterRef("position"))
            .filter(_condition(other, layer))
        )
        hits = hits.filter(Exists(neighbours))
    return hits.select_related("passage__edition__work__author").order_by(
        "edition__work__author__birth_year", "edition__work__cts_urn", "position"
    )


@dataclass
class Hit:
    token: Token
    words: list[Token]
    highlighted: set[int]

    @property
    def citation(self):
        return self.token.passage.citation

    @property
    def url(self):
        ids = ",".join(str(pk) for pk in sorted(self.highlighted))
        return f"{self.token.passage.get_absolute_url()}?mots={ids}#mot-{self.token.pk}"


def _nearby_words(tokens, reach):
    ranges = Q(pk__in=[])
    for token in tokens:
        ranges |= Q(
            edition_id=token.edition_id,
            position__range=(token.position - reach, token.position + reach),
        )
    nearby = defaultdict(dict)
    fields = ("id", "edition_id", "position", "form", "norm", "before", "after")
    for word in Token.objects.filter(ranges).only(*fields):
        nearby[word.edition_id][word.position] = word
    return nearby


def build_hits(tokens, terms, distance=5, ordered=False, layer=None):
    """Hits with the words around them, the words matching a term being highlighted."""
    tokens = list(tokens)
    if not tokens:
        return []
    nearby = _nearby_words(tokens, distance + CONTEXT_WORDS)
    lemmas = defaultdict(set)
    if any(term.lemma for term in terms):
        layer = layer or default_layer()
        ids = [word.pk for words in nearby.values() for word in words.values()]
        analyses = TokenAnalysis.objects.filter(layer=layer, token_id__in=ids)
        for token_id, lemma in analyses.values_list("token_id", "lemma_norm"):
            lemmas[token_id].add(lemma)

    def matches(term, word):
        values = lemmas[word.pk] if term.lemma else {word.norm}
        return any(term.matches(value) for value in values)

    hits = []
    for token in tokens:
        words = nearby[token.edition_id]
        highlighted = {token.pk}
        positions = [token.position]
        lowest = token.position + 1 if ordered else token.position - distance
        for term in terms[1:]:
            for position in range(lowest, token.position + distance + 1):
                word = words.get(position)
                if position != token.position and word is not None and matches(term, word):
                    highlighted.add(word.pk)
                    positions.append(position)
        start, end = min(positions) - CONTEXT_WORDS, max(positions) + CONTEXT_WORDS
        window = [words[p] for p in range(start, end + 1) if p in words]
        hits.append(Hit(token, window, highlighted))
    return hits


def author_distribution(hits):
    """(author, number of hits) pairs, in chronological order."""
    rows = hits.order_by().values("edition__work__author").annotate(count=Count("pk"))
    authors = Author.objects.in_bulk([row["edition__work__author"] for row in rows])
    pairs = [(authors[row["edition__work__author"]], row["count"]) for row in rows]
    return sorted(pairs, key=lambda pair: (pair[0].birth_year is None, pair[0].birth_year or 0))


@dataclass(frozen=True)
class CorpusVersion:
    """What was searched: every absence is reported with this version (rule 7)."""

    sources: tuple[str, ...]
    edition_count: int
    imported_at: object
    layer: str = ""

    @property
    def label(self):
        label = "Perseus " + ", ".join(version[:7] for version in self.sources)
        return f"{label} · {self.layer}" if self.layer else label


def corpus_version():
    editions = Edition.objects.filter(is_current=True)
    sources = tuple(sorted(set(editions.values_list("source_version", flat=True))))
    imported_at = editions.aggregate(last=Max("imported_at"))["last"]
    layer = default_layer()
    return CorpusVersion(sources, editions.count(), imported_at, layer.label if layer else "")
