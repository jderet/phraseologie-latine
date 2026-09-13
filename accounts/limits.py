"""Limits of new accounts, lifted by a first validated contribution (``User.is_confirmed``)."""

import re

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from moderation.models import Revision
from moderation.registry import uncounted_models

from .roles import is_reviewer

LINK_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://|www\.", re.IGNORECASE)


class ContributionLimitReached(PermissionDenied):
    pass


def is_limited(user):
    return not (user.is_confirmed or is_reviewer(user))


def contributions_today(user):
    """Contents created today; changes, and parts of contents such as sentences, do not count."""
    start_of_day = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    uncounted = ContentType.objects.get_for_models(*uncounted_models()).values()
    return (
        Revision.objects.filter(
            author=user, created_at__gte=start_of_day, action=Revision.Action.CREATE
        )
        .exclude(content_type__in=list(uncounted))
        .count()
    )


def check_can_contribute(user, counted=True):
    """Refuse inactive users; refuse new accounts at their limit for a counted creation."""
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    limit = settings.NEW_ACCOUNT_DAILY_LIMIT
    if counted and is_limited(user) and contributions_today(user) >= limit:
        message = ngettext(
            "Un nouveau compte peut faire %(limit)d contribution par jour, jusqu’à sa première "
            "contribution validée.",
            "Un nouveau compte peut faire %(limit)d contributions par jour, jusqu’à sa première "
            "contribution validée.",
            limit,
        )
        raise ContributionLimitReached(message % {"limit": limit})


def validate_no_links(value):
    if value and LINK_PATTERN.search(value):
        raise ValidationError(
            _(
                "Les liens ne sont pas autorisés tant que le compte n’a pas de contribution "
                "validée."
            ),
            code="links_not_allowed",
        )


def check_text_for_links(user, *texts):
    if is_limited(user):
        for text in texts:
            validate_no_links(text)
