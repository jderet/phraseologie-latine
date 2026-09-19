"""Concordance of the translations: where a word or an expression appears in the published
versions, on the Latin side or on the side of the source texts, with its sentence in regard.

Only the latest public step of each published version is searched (rule 8)."""

import re

from django.utils.html import format_html, format_html_join

from corpus.timeouts import TimeLimit

from .models import Segment, StepSentence, TranslationVersion, VersionStep
from .steps import public_step, sentence_at

LATIN, SOURCE = "latin", "source"
MIN_LENGTH = 2
MAX_RESULTS = 60
MAX_SCANNED = 400


def search(query, side=LATIN):
    """[{version, segment, latin, step}] of the public sentences containing ``query``.

    Returns (results, exceeded): exceeded is true when the search took too long.
    """
    needle = " ".join((query or "").split())
    if len(needle) < MIN_LENGTH:
        return [], False
    with TimeLimit(seconds=4) as limit:
        if side == SOURCE:
            results = _in_sources(needle)
        else:
            results = _in_latin(needle)
    if limit.exceeded:
        return [], True
    return results, False


def _in_latin(needle):
    rows = (
        StepSentence.objects.filter(
            text__icontains=needle,
            step__in=VersionStep.objects.public(),
            step__version__project__is_hidden=False,
        )
        .select_related("step__version__project", "step__version__author", "segment")
        .order_by("-step__created_at", "-pk")[:MAX_SCANNED]
    )
    results, seen, steps = [], set(), {}
    for row in rows:
        version = row.step.version
        key = (version.pk, row.segment_id)
        if key in seen:
            continue
        seen.add(key)
        if version.pk not in steps:
            steps[version.pk] = public_step(version)
        step = steps[version.pk]
        # Only the text the public sees now: a later step may have changed the sentence.
        if step is None or sentence_at(step, row.segment_id) != row.text:
            continue
        results.append(
            {"version": version, "segment": row.segment, "latin": row.text, "step": step}
        )
        if len(results) >= MAX_RESULTS:
            break
    return results


def _in_sources(needle):
    segments = (
        Segment.objects.filter(text__icontains=needle, source_text__is_hidden=False)
        .select_related("source_text")
        .order_by("source_text", "position")[:MAX_SCANNED]
    )
    by_text = {}
    for segment in segments:
        by_text.setdefault(segment.source_text_id, []).append(segment)
    versions = (
        TranslationVersion.objects.filter(
            project__source_text_id__in=by_text,
            state=TranslationVersion.State.PUBLISHED,
            is_hidden=False,
            project__is_hidden=False,
        )
        .select_related("project", "author")
        .order_by("project", "published_at")
    )
    results = []
    for version in versions:
        step = public_step(version)
        if step is None:
            continue
        for segment in by_text[version.project.source_text_id]:
            latin = sentence_at(step, segment.pk)
            if latin:
                results.append(
                    {"version": version, "segment": segment, "latin": latin, "step": step}
                )
            if len(results) >= MAX_RESULTS:
                return results
    return results


def highlight(text, needle):
    """The text with each occurrence of ``needle`` marked, case ignored; all escaped."""
    needle = " ".join((needle or "").split())
    if not needle:
        return format_html("{}", text)
    parts = re.split(f"({re.escape(needle)})", text, flags=re.IGNORECASE)
    return format_html_join(
        "",
        "{}",
        (
            (format_html("<mark>{}</mark>", part) if index % 2 else format_html("{}", part),)
            for index, part in enumerate(parts)
        ),
    )
