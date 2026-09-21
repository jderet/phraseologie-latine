"""Figures, queues and recent activity shown on the administrators' dashboard."""

from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from corpus.search import corpus_version, default_layer
from justifications.models import Challenge, Justification
from moderation.models import Report, Revision
from phraseology.models import Attestation, Candidate, NegativeSearch, Unit
from translations.models import SegmentVariant, SourceProposal, TranslationVersion

from .models import User


def key_figures():
    week_ago = timezone.now() - timedelta(days=7)
    return {
        "active_users": User.objects.filter(is_active=True).count(),
        "pending_users": User.objects.filter(
            is_active=False, last_login=None, anonymized_at=None
        ).count(),
        "new_users": User.objects.filter(date_joined__gte=week_ago).count(),
        "units": Unit.objects.exclude(status=Unit.Status.DRAFT).count(),
        "validated_attestations": Attestation.objects.filter(
            level=Attestation.Level.VALIDATED
        ).count(),
        "published_versions": TranslationVersion.objects.filter(
            state=TranslationVersion.State.PUBLISHED
        ).count(),
        "justifications": Justification.objects.count(),
    }


def queues():
    return {
        "reports": Report.objects.filter(status=Report.Status.OPEN).count(),
        "units": Unit.objects.filter(status=Unit.Status.PROPOSED).count(),
        "candidates": Candidate.objects.filter(status=Candidate.Status.PENDING).count(),
        "challenges": Challenge.objects.filter(status=Challenge.Status.OPEN).count(),
        "source_proposals": SourceProposal.objects.filter(
            status=SourceProposal.Status.OPEN
        ).count(),
        "variants": SegmentVariant.objects.filter(
            status=SegmentVariant.Status.PROPOSAL,
            decision=SegmentVariant.Decision.PENDING,
            is_hidden=False,
        ).count(),
    }


def recent_activity():
    return {
        "revisions": Revision.objects.select_related("author", "content_type")[:20],
        "users": User.objects.order_by("-date_joined")[:10],
        "negative_searches": NegativeSearch.objects.values("expression")
        .annotate(count=Count("pk"))
        .order_by("-count", "expression")[:10],
    }


def last_backup():
    """Date of the newest dump written by deploy/backup.sh, or None."""
    directory = Path(settings.BASE_DIR) / "backups"
    dumps = sorted(directory.glob("phraseologie-*.dump")) if directory.is_dir() else []
    if not dumps:
        return None
    return timezone.datetime.fromtimestamp(
        dumps[-1].stat().st_mtime, tz=timezone.get_current_timezone()
    )


def technical_state():
    layer = default_layer()
    return {
        "layer": layer.label if layer else None,
        "corpus_version": corpus_version().label,
        "daily_limit": settings.NEW_ACCOUNT_DAILY_LIMIT,
        "skip_email_verification": settings.SIGNUP_SKIP_EMAIL_VERIFICATION,
        "last_backup": last_backup(),
    }
