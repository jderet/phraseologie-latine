"""How the attestations of a unit realize it, so that they can be reviewed in batches."""

from collections import defaultdict

from django.utils.translation import gettext

from corpus.models import TokenAnalysis

from .models import Attestation
from .schema import schema_lemmas


def attestation_shapes(ids, layer, edges):
    """A label for each attestation: the lemmas of its words in the order of the text.

    Adjacent words are separated by a space and words apart by « … »; a passive adds
    « (passif) ». Attestations with the same label realize the unit in the same way: word
    order, inserted words, passive. A word without a lemma of the schema keeps its form.
    """
    words = defaultdict(list)
    rows = Attestation.tokens.through.objects.filter(attestation_id__in=ids).values_list(
        "attestation_id", "token_id", "token__position", "token__norm"
    )
    for attestation_id, token_id, position, norm in rows:
        words[attestation_id].append((position, token_id, norm))
    analyses = defaultdict(list)
    if layer is not None:
        token_ids = {token_id for items in words.values() for _position, token_id, _norm in items}
        rows = TokenAnalysis.objects.filter(layer=layer, token_id__in=token_ids).values_list(
            "token_id", "lemma_norm", "deprel"
        )
        for token_id, lemma, deprel in rows:
            analyses[token_id].append((lemma, deprel))
    lemmas = set(schema_lemmas(edges))
    shapes = {}
    for attestation_id, items in words.items():
        parts, previous, passive = [], None, False
        for position, token_id, norm in sorted(items):
            if previous is not None:
                parts.append(" " if position == previous + 1 else " … ")
            found = [lemma for lemma, _deprel in analyses[token_id] if lemma in lemmas]
            parts.append(found[0] if found else norm)
            passive = passive or any(deprel.endswith(":pass") for _l, deprel in analyses[token_id])
            previous = position
        shape = "".join(parts)
        shapes[attestation_id] = (
            gettext("%(shape)s (passif)") % {"shape": shape} if passive else shape
        )
    return shapes
