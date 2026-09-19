"""Public feeds: what happened in a project, what a contributor did, day by day."""

import datetime as dt
from collections import Counter

from django.db.models import Count
from django.utils import timezone

from moderation.registry import can_view

from .models import Event, Verb

FEED_LENGTH = 50
CALENDAR_WEEKS = 52

# Events that are only for the people concerned, never in a feed.
PRIVATE_VERBS = {Verb.MENTIONED, Verb.MEMBER_INVITED, Verb.MEMBER_DECLINED}


def _visible(user, events, limit):
    shown = []
    for event in events:
        target = event.target
        if target is not None and can_view(user, target):
            shown.append(event)
            if len(shown) >= limit:
                break
    return shown


def public_events(queryset):
    return (
        queryset.filter(is_public=True)
        .exclude(verb__in=PRIVATE_VERBS)
        .select_related("actor", "project", "content_type")
        .order_by("-created_at", "-pk")
    )


def project_feed(user, project, limit=FEED_LENGTH):
    """The latest public events of a project the reader may still see."""
    events = public_events(Event.objects.filter(project=project))[: limit * 3]
    return _visible(user, events, limit)


def contributor_feed(user, contributor, limit=20):
    events = public_events(Event.objects.filter(actor=contributor))[: limit * 3]
    return _visible(user, events, limit)


def activity_calendar(contributor, today=None):
    """Weeks of public activity, oldest first: each week lists seven days (Monday first) with
    the number of public events and a level from 0 to 4, like the calendar of GitHub."""
    today = today or timezone.localdate()
    start = today - dt.timedelta(days=today.weekday()) - dt.timedelta(weeks=CALENDAR_WEEKS - 1)
    rows = (
        public_events(Event.objects.filter(actor=contributor, created_at__date__gte=start))
        .order_by()
        .values("created_at__date")
        .annotate(count=Count("pk"))
    )
    counts = Counter({row["created_at__date"]: row["count"] for row in rows})
    weeks = []
    for week in range(CALENDAR_WEEKS):
        days = []
        for weekday in range(7):
            day = start + dt.timedelta(weeks=week, days=weekday)
            count = counts.get(day, 0) if day <= today else None
            days.append({"date": day, "count": count, "level": _level(count)})
        weeks.append(days)
    return {"weeks": weeks, "total": sum(counts.values())}


def _level(count):
    if not count:
        return 0
    if count < 2:
        return 1
    if count < 4:
        return 2
    if count < 8:
        return 3
    return 4
