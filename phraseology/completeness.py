"""Completeness of the annotation: passages a reviewer declares entirely reviewed.

In such a passage every unit is noted; the share of these passages measures how far a work of
the core is surveyed. A declaration keeps its date and the version of the corpus, and can be
withdrawn.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext

from accounts.roles import is_reviewer
from corpus.models import Passage
from corpus.search import corpus_version

from .models import Attestation, PassageReview


def current_reviews(passages):
    """The standing declarations about some passages, by passage."""
    reviews = PassageReview.objects.filter(passage__in=passages, is_withdrawn=False)
    return {review.passage_id: review for review in reviews.select_related("reviewed_by")}


@transaction.atomic
def mark_reviewed(passage, reviewer):
    """A reviewer declares that every unit of a passage is noted."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    standing = PassageReview.objects.select_for_update().filter(passage=passage, is_withdrawn=False)
    if standing.exists():
        raise ValidationError(
            gettext("Ce passage est déjà déclaré entièrement relu."), code="already_reviewed"
        )
    return PassageReview.objects.create(
        passage=passage, reviewed_by=reviewer, corpus_version=corpus_version().label
    )


@transaction.atomic
def withdraw_review(passage, reviewer):
    """A reviewer withdraws the declaration, when a unit of the passage turns out to be missing."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    return PassageReview.objects.filter(passage=passage, is_withdrawn=False).update(
        is_withdrawn=True, withdrawn_by=reviewer, withdrawn_at=timezone.now()
    )


def _count_by_work(queryset, path):
    return dict(queryset.order_by().values_list(path).annotate(count=Count("pk")))


def work_progress(works):
    """For each work, the passages of its current edition, those entirely reviewed, and its
    validated attestations; three queries whatever the number of works."""
    works = list(works)
    current = {"edition__is_current": True, "edition__work__in": works}
    totals = _count_by_work(Passage.objects.filter(**current), "edition__work")
    reviewed = _count_by_work(
        PassageReview.objects.filter(
            is_withdrawn=False,
            passage__edition__is_current=True,
            passage__edition__work__in=works,
        ),
        "passage__edition__work",
    )
    validated = _count_by_work(
        Attestation.objects.active().filter(
            is_hidden=False,
            status=Attestation.Status.VALIDATED,
            passage__edition__is_current=True,
            passage__edition__work__in=works,
        ),
        "passage__edition__work",
    )
    rows = []
    for work in works:
        total, done = totals.get(work.pk, 0), reviewed.get(work.pk, 0)
        rows.append(
            {
                "work": work,
                "total": total,
                "reviewed": done,
                "percent": round(100 * done / total) if total else 0,
                "validated": validated.get(work.pk, 0),
            }
        )
    return rows


def passages_to_review(work):
    """The passages of the current edition of a work not declared entirely reviewed, in order."""
    reviewed = PassageReview.objects.filter(is_withdrawn=False).values("passage")
    return (
        Passage.objects.filter(edition__work=work, edition__is_current=True)
        .exclude(pk__in=reviewed)
        .order_by("order")
    )


def attestation_counts(passages):
    """Active attestations beginning in some passages, by passage: all, and those validated."""
    attestations = Attestation.objects.active().filter(passage__in=passages, is_hidden=False)
    return (
        _count_by_work(attestations, "passage"),
        _count_by_work(attestations.filter(status=Attestation.Status.VALIDATED), "passage"),
    )
