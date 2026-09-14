"""Strength of association between two words linked by a syntactic relation (Q16).

The score is Dunning's log-likelihood ratio (G²), computed on the 2×2 table of the pair:
how often the governing word and the dependent occur together in the relation, how often
each occurs in it with other words, and how many pairs the relation has in all. It is
positive when the pair occurs more often than chance would have it, negative otherwise.
"""

import math


def _term(observed, expected):
    return observed * math.log(observed / expected) if observed > 0 else 0.0


def log_likelihood(pair, head, dependent, total):
    """Signed G² of a pair seen ``pair`` times, its words ``head`` and ``dependent`` times.

    ``head`` and ``dependent`` count the pairs of the relation that contain each word;
    ``total`` counts all the pairs of the relation.
    """
    if not 0 < pair <= min(head, dependent) or max(head, dependent) > total:
        raise ValueError("Inconsistent frequencies.")
    observed = (
        pair,
        head - pair,
        dependent - pair,
        total - head - dependent + pair,
    )
    expected = (
        head * dependent / total,
        head * (total - dependent) / total,
        (total - head) * dependent / total,
        (total - head) * (total - dependent) / total,
    )
    score = 2 * sum(_term(o, e) for o, e in zip(observed, expected, strict=True))
    return score if pair >= expected[0] else -score
