"""Statistical profiles of collocations: the words a lemma goes with, by relation (Q33).

The pairs are counted in the analysed corpus on the Mac (``manage.py compute_collocations``)
for three parts of the corpus, and ranked by log-likelihood like the candidates; the server
only reads them. They come from the automatic analysis and are shown as found automatically,
with the version of the corpus (rules 4 and 7).
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from corpus.search import corpus_version

from .association import log_likelihood
from .candidates import pair_counts
from .models import Collocation

MIN_FREQUENCY = 3
BATCH_SIZE = 5000
SHOWN = 20

SCOPES = {
    Collocation.Scope.CORE: {"core_only": True, "prose_only": False},
    Collocation.Scope.PROSE: {"core_only": False, "prose_only": True},
    Collocation.Scope.ALL: {"core_only": False, "prose_only": False},
}

# The sections of a profile: relation, the place of the lemma in it, title.
SECTIONS = (
    ("obj", "head", _("Objets (et sujets du passif)")),
    ("nsubj", "head", _("Sujets")),
    ("obl", "head", _("Compléments du verbe")),
    ("advmod", "head", _("Adverbes")),
    ("amod", "head", _("Adjectifs épithètes")),
    ("nmod", "head", _("Compléments du nom")),
    ("obj", "dependent", _("Verbes dont il est l’objet")),
    ("nsubj", "dependent", _("Verbes dont il est le sujet")),
    ("obl", "dependent", _("Verbes dont il est le complément")),
    ("amod", "dependent", _("Noms qu’il qualifie")),
    ("advmod", "dependent", _("Mots qu’il modifie")),
    ("nmod", "dependent", _("Noms dont il est le complément")),
)


@transaction.atomic
def compute_collocations(layer, min_frequency=MIN_FREQUENCY):
    """Count and score the pairs of each part of the corpus, replacing the previous count."""
    version = corpus_version().label
    now = timezone.now()
    counts = {}
    for scope, options in SCOPES.items():
        rows = [
            Collocation(
                scope=scope,
                head=head,
                relation=relation,
                dependent=dependent,
                frequency=pair,
                score=round(log_likelihood(pair, heads, dependents, total), 2),
                layer=layer,
                corpus_version=version,
                computed_at=now,
            )
            for head, relation, dependent, pair, heads, dependents, total in pair_counts(
                layer, min_frequency=min_frequency, **options
            )
        ]
        Collocation.objects.filter(scope=scope).delete()
        Collocation.objects.bulk_create(rows, batch_size=BATCH_SIZE)
        counts[scope] = len(rows)
    return counts


def profile(lemma, scope, shown=SHOWN):
    """The sections of a lemma's profile with their best collocates; empty sections are left out.

    Pairs less frequent than chance would have them (negative score) are not shown.
    """
    collocations = Collocation.objects.filter(scope=scope, score__gte=0)
    sections = []
    for relation, role, title in SECTIONS:
        rows = list(
            collocations.filter(relation=relation, **{role: lemma}).order_by("-score", "pk")[:shown]
        )
        for row in rows:
            row.collocate = row.dependent if role == "head" else row.head
        if rows:
            sections.append({"title": title, "role": role, "rows": rows})
    return sections


def profile_computed(scope):
    """The version of the corpus and the date of the last count for a part of the corpus."""
    return (
        Collocation.objects.filter(scope=scope)
        .order_by()
        .values("corpus_version", "computed_at")
        .first()
    )
