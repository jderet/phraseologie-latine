"""Where the schema of a unit occurs in the analysed corpus, and how often.

The matches come from the automatic analysis (lemmas and dependencies of the default
layer): they are counted and shown as found automatically, with the version of the corpus
(rules 4 and 7), never as attestations checked by people.
"""

from django.db.models import Count, Exists, OuterRef, Q

from corpus.models import Author, Token, TokenAnalysis


def _relation_condition(relations):
    """A relation without subtype also matches its subtypes: obl matches obl:arg."""
    condition = Q(pk__in=[])
    for relation in relations:
        condition |= Q(deprel__iexact=relation)
        if ":" not in relation:
            condition |= Q(deprel__istartswith=f"{relation}:")
    return condition


def _dependents(lemma, edges, layer):
    """Conditions on the analysis of a word: it governs the dependents of ``lemma``."""
    conditions = []
    for edge in edges:
        if edge.head != lemma:
            continue
        dependents = TokenAnalysis.objects.filter(
            _relation_condition(edge.relations),
            layer=layer,
            head_id=OuterRef("token_id"),
            head_part=OuterRef("part"),
            lemma_norm=edge.dependent,
        ).filter(*_dependents(edge.dependent, edges, layer))
        conditions.append(Exists(dependents))
    return conditions


def schema_matches(edges, layer, core_only=False):
    """Analyses of the governing word of every occurrence of a schema, in current editions."""
    root = edges[0].head
    matches = TokenAnalysis.objects.filter(
        layer=layer, lemma_norm=root, token__edition__is_current=True
    ).filter(*_dependents(root, edges, layer))
    if core_only:
        matches = matches.filter(token__edition__work__is_core=True)
    return matches


def occurrence_tokens(match, edges, layer):
    """The words of one occurrence: the governing word, then its dependents in the schema."""
    tokens = [match.token]
    heads = {edges[0].head: match}
    for edge in edges:
        head = heads.get(edge.head)
        if head is None:
            continue
        dependent = (
            TokenAnalysis.objects.filter(
                _relation_condition(edge.relations),
                layer=layer,
                head_id=head.token_id,
                head_part=head.part,
                lemma_norm=edge.dependent,
            )
            .filter(*_dependents(edge.dependent, edges, layer))
            .select_related("token")
            .order_by("token__position")
            .first()
        )
        if dependent is not None:
            heads[edge.dependent] = dependent
            tokens.append(dependent.token)
    return sorted({token.pk: token for token in tokens}.values(), key=lambda t: t.position)


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
