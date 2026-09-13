"""Searching the corpus by word form, with filters and context.

A query has one to three terms. Each term is one or more patterns separated by "|"; a
pattern ending with "*" matches the beginning of a word. Forms are compared in their
normalized spelling (corpus.text.normalize). Lemma search arrives with the linguistic
analysis layer.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.db.models import Count, Exists, Max, OuterRef, Q

from .models import Author, Edition, Token
from .text import normalize

CONTEXT_WORDS = 8


def parse_term(text):
    """Patterns of a term: "cap* | cep*" gives ["cap*", "cep*"]."""
    return [part.strip() for part in (text or "").split("|") if part.strip().rstrip("*")]


def _pattern_rules(patterns):
    return [(normalize(pattern.rstrip("*")), pattern.endswith("*")) for pattern in patterns]


def _condition(patterns):
    condition = Q(pk__in=[])
    for value, is_prefix in _pattern_rules(patterns):
        condition |= Q(norm__startswith=value) if is_prefix else Q(norm=value)
    return condition


def _matcher(patterns):
    rules = _pattern_rules(patterns)
    return lambda norm: any(
        norm.startswith(value) if is_prefix else norm == value for value, is_prefix in rules
    )


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


def search_tokens(terms, distance=5, ordered=False, filters=None):
    """Words matching the first term that have the other terms within ``distance`` words.

    With ``ordered``, the other terms must come after the first one.
    """
    first, *others = terms
    hits = Token.objects.filter(edition__is_current=True).filter(_condition(first))
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
            .filter(_condition(other))
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


def build_hits(tokens, terms, distance=5, ordered=False):
    """Hits with the words around them, the words matching a term being highlighted."""
    tokens = list(tokens)
    if not tokens:
        return []
    reach = distance + CONTEXT_WORDS
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
    matchers = [_matcher(term) for term in terms[1:]]
    hits = []
    for token in tokens:
        words = nearby[token.edition_id]
        highlighted = {token.pk}
        positions = [token.position]
        lowest = token.position + 1 if ordered else token.position - distance
        for matches in matchers:
            for position in range(lowest, token.position + distance + 1):
                word = words.get(position)
                if position != token.position and word is not None and matches(word.norm):
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

    @property
    def label(self):
        return "Perseus " + ", ".join(version[:7] for version in self.sources)


def corpus_version():
    editions = Edition.objects.filter(is_current=True)
    sources = tuple(sorted(set(editions.values_list("source_version", flat=True))))
    imported_at = editions.aggregate(last=Max("imported_at"))["last"]
    return CorpusVersion(sources, editions.count(), imported_at)
