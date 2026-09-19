"""Where the schema of a unit occurs in the analysed corpus, and how often.

The matches come from the automatic analysis (lemmas and dependencies of the default
layer): they are counted and shown as found automatically, with the version of the corpus
(rules 4 and 7), never as attestations checked by people.
"""

from collections import Counter

from django.db.models import Count, Exists, OuterRef, Q

from corpus.models import Author, Token, TokenAnalysis

from .schema import SLOT, corpus_edges

# Governing words looked up together when gathering the words of many occurrences.
CHUNK_SIZE = 5000
# Occurrences whose open dependent is counted by lemma.
SLOT_LIMIT = 50000


def _word(lemma, cases):
    """Conditions on the analysis of a word: its lemma, unless open, and its case if given."""
    condition = {} if lemma == SLOT else {"lemma_norm": lemma}
    if lemma in cases:
        condition["feats__contains"] = f"Case={cases[lemma]}"
    return condition


def _relation_condition(relations):
    """A relation without subtype also matches its subtypes: obl matches obl:arg."""
    condition = Q(pk__in=[])
    for relation in relations:
        condition |= Q(deprel__iexact=relation)
        if ":" not in relation:
            condition |= Q(deprel__istartswith=f"{relation}:")
    return condition


def _dependents(lemma, edges, layer, cases):
    """Conditions on the analysis of a word: it governs the required dependents of ``lemma``.

    An optional relation, and what depends on it, is not required.
    """
    conditions = []
    for edge in edges:
        if edge.head != lemma or edge.optional:
            continue
        dependents = TokenAnalysis.objects.filter(
            _relation_condition(edge.relations),
            layer=layer,
            head_id=OuterRef("token_id"),
            head_part=OuterRef("part"),
            **_word(edge.dependent, cases),
        ).filter(*_dependents(edge.dependent, edges, layer, cases))
        conditions.append(Exists(dependents))
    return conditions


def schema_matches(edges, layer, core_only=False):
    """Analyses of the governing word of every occurrence of a schema, in current editions.

    The governing word is the one of the analysis: the noun of a prepositional phrase at the
    root of a schema, not its preposition.
    """
    edges, cases = corpus_edges(edges)
    root = edges[0].head
    matches = TokenAnalysis.objects.filter(
        layer=layer, token__edition__is_current=True, **_word(root, cases)
    ).filter(*_dependents(root, edges, layer, cases))
    if core_only:
        matches = matches.filter(token__edition__work__is_core=True)
    return matches


def occurrence_parts(roots, edges, layer):
    """For each occurrence, the (word, part) of each lemma of the schema, and word positions.

    ``roots`` are (word, part, position) of the governing word of each occurrence; for each
    relation of the schema, the first dependent in the text is kept; the words of an optional
    relation are there when the occurrence has them. A few queries serve any number of
    occurrences.
    """
    edges, cases = corpus_edges(edges)
    roots = list(roots)
    positions = {token_id: position for token_id, _part, position in roots}
    found = [{edges[0].head: (token_id, part)} for token_id, part, _position in roots]
    for edge in edges:
        heads = sorted({item[edge.head][0] for item in found if edge.head in item})
        chosen = {}
        for start in range(0, len(heads), CHUNK_SIZE):
            dependents = (
                TokenAnalysis.objects.filter(
                    _relation_condition(edge.relations),
                    layer=layer,
                    head_id__in=heads[start : start + CHUNK_SIZE],
                    **_word(edge.dependent, cases),
                )
                .filter(*_dependents(edge.dependent, edges, layer, cases))
                .order_by("token__position")
                .values_list("head_id", "head_part", "token_id", "part", "token__position")
            )
            for head_id, head_part, token_id, part, position in dependents:
                chosen.setdefault((head_id, head_part), (token_id, part))
                positions[token_id] = position
        for item in found:
            dependent = chosen.get(item.get(edge.head))
            if dependent is not None:
                item[edge.dependent] = dependent
    return found, positions


def occurrence_words(roots, edges, layer):
    """The words of each occurrence, as word identifiers in textual order."""
    found, positions = occurrence_parts(roots, edges, layer)
    return [
        tuple(sorted({token_id for token_id, _part in item.values()}, key=positions.get))
        for item in found
    ]


def slot_fillers(matches, edges, layer, limit=SLOT_LIMIT):
    """The lemmas found in the open dependent of a query, the most frequent first."""
    roots = matches.order_by().values_list("token_id", "part", "token__position")[:limit]
    found, _positions = occurrence_parts(roots, edges, layer)
    filled = [item[SLOT] for item in found if SLOT in item]
    ids = sorted({token_id for token_id, _part in filled})
    lemmas = {}
    for start in range(0, len(ids), CHUNK_SIZE):
        rows = TokenAnalysis.objects.filter(
            layer=layer, token_id__in=ids[start : start + CHUNK_SIZE]
        ).values_list("token_id", "part", "lemma_norm")
        lemmas.update({(token_id, part): lemma for token_id, part, lemma in rows})
    counts = Counter(lemmas[key] for key in filled if key in lemmas)
    return sorted(counts.items(), key=lambda row: (-row[1], row[0]))


def occurrence_tokens(match, edges, layer):
    """The words of one occurrence: the governing word, then its dependents in the schema."""
    (ids,) = occurrence_words([(match.token_id, match.part, match.token.position)], edges, layer)
    return load_tokens(ids)


def count_by_author(matches):
    """Occurrences per author, in chronological order: (author, total, in the core)."""
    rows = (
        matches.order_by()
        .values("token__edition__work__author", "token__edition__work__is_core")
        .annotate(count=Count("pk"))
    )
    totals = {}
    for row in rows:
        total, core = totals.get(row["token__edition__work__author"], (0, 0))
        count = row["count"]
        totals[row["token__edition__work__author"]] = (
            total + count,
            core + (count if row["token__edition__work__is_core"] else 0),
        )
    authors = Author.objects.in_bulk(totals)
    return sorted(
        ((authors[pk], total, core) for pk, (total, core) in totals.items()),
        key=lambda row: (row[0].birth_year is None, row[0].birth_year or 0, row[0].pk),
    )


def load_tokens(ids):
    """Words with what their citation needs, in the order of ``ids``."""
    tokens = Token.objects.select_related("passage__edition__work__author").in_bulk(ids)
    return [tokens[pk] for pk in ids if pk in tokens]
