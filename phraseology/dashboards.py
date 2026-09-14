"""Following the annotation: what an annotator did, what waits for reviewers, public figures.

Figures of public contents leave drafts and hidden contents out (rule 8); an automatic
attestation is counted apart from those checked by people (rule 4).
"""

from django.db.models import Count, Prefetch, Q

from corpus.models import AnalysisCorrection, Passage, Token
from corpus.search import quotation

from .models import Attestation, AttestationDoubt, PassageReview, Sighting, Unit

RECENT = 30
PASSAGES_SHOWN = 50


def _by_status(queryset):
    return dict(queryset.order_by().values_list("status").annotate(count=Count("pk")))


def attestation_figures(attestations):
    """Attestations counted as they are shown: validated, proposed, automatic, rejected."""
    return attestations.aggregate(
        validated=Count("pk", filter=Q(status=Attestation.Status.VALIDATED)),
        proposed=Count(
            "pk",
            filter=Q(status=Attestation.Status.PROPOSED, level=Attestation.Level.VALIDATED),
        ),
        automatic=Count(
            "pk",
            filter=Q(status=Attestation.Status.PROPOSED, level=Attestation.Level.AUTOMATIC),
        ),
        rejected=Count("pk", filter=Q(status=Attestation.Status.REJECTED)),
    )


def _with_quotations(items):
    """Items that point to words, each given the quotation of its words."""
    tokens = Token.objects.select_related("passage__edition__work__author").order_by("position")
    items = list(items.prefetch_related(Prefetch("tokens", queryset=tokens)))
    for item in items:
        item.quotation = quotation(list(item.tokens.all()))
    return items


def annotator_summary(user):
    """What a user added in the texts: attestations, sightings, doubts and corrections."""
    attestations = Attestation.objects.active().filter(created_by=user, is_hidden=False)
    sightings = Sighting.objects.filter(created_by=user, is_hidden=False)
    doubts = AttestationDoubt.objects.filter(created_by=user, is_hidden=False)
    corrections = AnalysisCorrection.objects.filter(created_by=user, is_hidden=False)
    return {
        "attestation_figures": attestation_figures(attestations),
        "attestations": _with_quotations(
            attestations.select_related("unit").order_by("-created_at", "-pk")[:RECENT]
        ),
        "sighting_figures": _by_status(sightings),
        "sightings": _with_quotations(sightings.order_by("-created_at", "-pk")[:RECENT]),
        "doubt_figures": _by_status(doubts),
        "doubts": list(
            doubts.select_related(
                "attestation__unit", "attestation__passage__edition__work"
            ).order_by("-created_at", "-pk")[:RECENT]
        ),
        "correction_figures": _by_status(corrections),
        "corrections": list(
            corrections.select_related("token__passage__edition__work__author").order_by(
                "-created_at", "-pk"
            )[:RECENT]
        ),
    }


def reviewer_queue():
    """What waits for reviewers, the proposed attestations grouped by passage."""
    proposed = Attestation.objects.active().filter(
        is_hidden=False, status=Attestation.Status.PROPOSED, level=Attestation.Level.VALIDATED
    )
    rows = list(
        proposed.order_by()
        .values("passage")
        .annotate(count=Count("pk"))
        .order_by("-count")[:PASSAGES_SHOWN]
    )
    passages = Passage.objects.select_related("edition__work__author").in_bulk(
        [row["passage"] for row in rows]
    )
    doubts = AttestationDoubt.objects.filter(status=AttestationDoubt.Status.OPEN, is_hidden=False)
    contested = Attestation.objects.active().filter(is_contested=True, is_hidden=False)
    return {
        "proposed_total": proposed.count(),
        "groups": [
            {"passage": passages[row["passage"]], "count": row["count"]}
            for row in rows
            if row["passage"] in passages
        ],
        "automatic_in_core": Attestation.objects.active()
        .filter(
            is_hidden=False,
            status=Attestation.Status.PROPOSED,
            level=Attestation.Level.AUTOMATIC,
            passage__edition__work__is_core=True,
        )
        .count(),
        "doubts_total": doubts.count(),
        "doubts": list(
            doubts.select_related(
                "attestation__unit", "attestation__passage__edition__work__author", "created_by"
            )[:RECENT]
        ),
        "contested_total": contested.count(),
        "contested": list(
            contested.select_related("unit", "passage__edition__work__author")[:RECENT]
        ),
        "sightings_open": Sighting.objects.filter(
            status=Sighting.Status.OPEN, is_hidden=False
        ).count(),
        "corrections_proposed": AnalysisCorrection.objects.filter(
            status=AnalysisCorrection.Status.PROPOSED, is_hidden=False
        ).count(),
        "units_proposed": Unit.objects.filter(status=Unit.Status.PROPOSED, is_hidden=False).count(),
        "units_contested": Unit.objects.filter(
            status=Unit.Status.CONTESTED, is_hidden=False
        ).count(),
    }


def public_figures():
    """The figures of the annotation, as anyone may see them."""
    public_units = Unit.objects.filter(is_hidden=False).exclude(status=Unit.Status.DRAFT)
    attestations = Attestation.objects.active().filter(is_hidden=False, unit__in=public_units)
    core = {"edition__is_current": True, "edition__work__is_core": True}
    core_passages = Passage.objects.filter(**core).count()
    reviewed = PassageReview.objects.filter(
        is_withdrawn=False, **{f"passage__{key}": value for key, value in core.items()}
    ).count()
    return {
        "units": _by_status(public_units),
        "units_total": public_units.count(),
        "attestations": attestation_figures(attestations),
        "core_passages": core_passages,
        "reviewed": reviewed,
        "percent": round(100 * reviewed / core_passages, 1) if core_passages else 0,
        "sightings_open": Sighting.objects.filter(
            status=Sighting.Status.OPEN, is_hidden=False
        ).count(),
        "corrections_validated": AnalysisCorrection.objects.filter(
            status=AnalysisCorrection.Status.VALIDATED, is_hidden=False
        ).count(),
    }
