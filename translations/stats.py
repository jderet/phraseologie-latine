"""Figures of a version: sentences and words, who wrote what, the pace of the work."""

import datetime as dt
from collections import Counter

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.models import User
from moderation.models import Revision

from .editor import row_data, status_counts
from .models import TranslatedSegment, is_version_writer

PACE_DAYS = 30


def word_count(text):
    return len((text or "").split())


def version_stats(user, version, rows):
    """Figures of the text the user sees (``rows`` of the version page).

    The titles of the divisions are left out: only the sentences are counted.
    """
    rows = [row for row in rows if not row["segment"].level]
    translated = [row for row in rows if row["saved"]]
    source_words = sum(word_count(row["segment"].text) for row in rows)
    latin_words = sum(word_count(row["saved"]) for row in translated)
    writers = Counter()
    for row in translated:
        sentence = row["sentence"]
        writers[getattr(sentence, "written_by_id", None) or version.author_id] += 1
    people = User.objects.in_bulk(writers)
    shares = [
        {"user": people[user_id], "count": count, "percent": round(count * 100 / len(translated))}
        for user_id, count in writers.most_common()
        if user_id in people
    ]
    stats = {
        "sentences": len(rows),
        "translated": len(translated),
        "source_words": source_words,
        "latin_words": latin_words,
        "ratio": round(latin_words / source_words, 2) if source_words else None,
        "shares": shares,
        "steps": version.steps.count(),
        "justifications": sum(len(row["justifications"]) for row in rows),
    }
    if is_version_writer(user, version):
        for row in rows:
            row["data"] = row_data(row)
        stats["statuses"] = status_counts(rows)
        stats["pace"] = pace(version)
    return stats


def pace(version, days=PACE_DAYS):
    """[(date, number of sentences saved)] over the last days, for the writers."""
    since = timezone.localdate() - dt.timedelta(days=days - 1)
    ids = version.segments.values_list("pk", flat=True)
    rows = (
        Revision.objects.filter(
            content_type=ContentType.objects.get_for_model(TranslatedSegment),
            object_id__in=list(ids),
            created_at__date__gte=since,
        )
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("pk"))
    )
    counts = {row["day"]: row["count"] for row in rows}
    top = max(counts.values(), default=0) or 1
    bars = []
    for offset in range(days):
        day = since + dt.timedelta(days=offset)
        count = counts.get(day, 0)
        height = count * 56 / top
        bars.append(
            {
                "day": day,
                "count": count,
                "x": offset * 10,
                "y": f"{60 - height:.1f}",
                "height": f"{height:.1f}",
            }
        )
    return bars
