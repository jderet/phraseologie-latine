"""Candidate units extracted from the analysed corpus: syntactic pairs ranked by association (Q16).

The extraction runs on the Mac (``manage.py extract_candidates``); the server only shows the
queue, where people retain a candidate by making a unit of it, or reject it.
"""

from django.db import connection, transaction
from django.utils import timezone

from corpus.search import corpus_version

from .association import log_likelihood
from .models import Candidate

# Relations kept, with their subtypes, as in schemas; a passive subject counts as an object
# (bellum geritur, bellum gerere). Negation (non) is left aside.
RELATIONS = ["obj", "obl", "amod", "advmod", "nmod", "nsubj"]
EXCLUDED_RELATIONS = ["advmod:neg"]
HEAD_TAGS = ["VERB", "NOUN", "ADJ"]
DEPENDENT_TAGS = ["NOUN", "ADJ", "ADV", "VERB"]
MIN_FREQUENCY = 5
# A log-likelihood above 10.83 means the pair is more frequent than chance, with p < 0.001.
MIN_SCORE = 10.83
BATCH_SIZE = 2000

PAIRS_SQL = """
WITH pairs AS (
  SELECT h.lemma_norm AS head,
         CASE WHEN d.deprel = 'nsubj:pass' THEN 'obj' ELSE split_part(d.deprel, ':', 1) END AS rel,
         d.lemma_norm AS dep
  FROM corpus_tokenanalysis d
  JOIN corpus_tokenanalysis h
    ON h.layer_id = d.layer_id AND h.token_id = d.head_id AND h.part = d.head_part
  JOIN corpus_token t ON t.id = d.token_id
  JOIN corpus_edition e ON e.id = t.edition_id
  JOIN corpus_work w ON w.id = e.work_id
  WHERE d.layer_id = %(layer)s AND e.is_current AND (w.is_core OR NOT %(core_only)s)
    AND (w.form = 'prose' OR NOT %(prose_only)s)
    AND split_part(d.deprel, ':', 1) = ANY(%(relations)s)
    AND d.deprel <> ALL(%(excluded_relations)s)
    AND d.upos = ANY(%(dependent_tags)s) AND h.upos = ANY(%(head_tags)s)
    AND d.lemma_norm ~ '^[a-z]{2,}$' AND h.lemma_norm ~ '^[a-z]{2,}$'
    AND h.lemma_norm <> 'sum'
),
counts AS (SELECT head, rel, dep, count(*) AS n FROM pairs GROUP BY head, rel, dep)
SELECT head, rel, dep, n, head_n, dep_n, total FROM (
  SELECT head, rel, dep, n,
         sum(n) OVER (PARTITION BY head, rel) AS head_n,
         sum(n) OVER (PARTITION BY dep, rel) AS dep_n,
         sum(n) OVER (PARTITION BY rel) AS total
  FROM counts
) marginals
WHERE n >= %(min_frequency)s
"""


def pair_counts(layer, core_only=True, min_frequency=MIN_FREQUENCY, prose_only=False):
    """(head, relation, dependent, pair, head, dependent, total) counts of the analysed pairs."""
    params = {
        "layer": layer.pk,
        "core_only": core_only,
        "prose_only": prose_only,
        "relations": RELATIONS,
        "excluded_relations": EXCLUDED_RELATIONS,
        "head_tags": HEAD_TAGS,
        "dependent_tags": DEPENDENT_TAGS,
        "min_frequency": min_frequency,
    }
    with connection.cursor() as cursor:
        cursor.execute(PAIRS_SQL, params)
        return [
            (head, relation, dependent, int(pair), int(heads), int(dependents), int(total))
            for head, relation, dependent, pair, heads, dependents, total in cursor.fetchall()
        ]


@transaction.atomic
def extract_candidates(layer, core_only=True, min_frequency=MIN_FREQUENCY, min_score=MIN_SCORE):
    """Store the associated pairs of the analysed corpus as candidates.

    Decisions already taken are kept; pending candidates that no longer qualify are removed.
    """
    version = corpus_version().label
    now = timezone.now()
    existing = {
        (candidate.head, candidate.relation, candidate.dependent): candidate
        for candidate in Candidate.objects.all()
    }
    kept, created, updated = set(), [], []
    for head, relation, dependent, pair, heads, dependents, total in pair_counts(
        layer, core_only, min_frequency
    ):
        score = log_likelihood(pair, heads, dependents, total)
        if score < min_score:
            continue
        key = (head, relation, dependent)
        kept.add(key)
        values = {
            "frequency": pair,
            "score": round(score, 2),
            "layer": layer,
            "corpus_version": version,
            "extracted_at": now,
        }
        candidate = existing.get(key)
        if candidate is None:
            created.append(Candidate(head=head, relation=relation, dependent=dependent, **values))
            continue
        for name, value in values.items():
            setattr(candidate, name, value)
        updated.append(candidate)
    stale = [
        candidate.pk
        for key, candidate in existing.items()
        if key not in kept and candidate.status == Candidate.Status.PENDING
    ]
    Candidate.objects.filter(pk__in=stale).delete()
    Candidate.objects.bulk_create(created, batch_size=BATCH_SIZE)
    Candidate.objects.bulk_update(
        updated,
        ["frequency", "score", "layer", "corpus_version", "extracted_at"],
        batch_size=BATCH_SIZE,
    )
    return {"created": len(created), "updated": len(updated), "removed": len(stale)}
