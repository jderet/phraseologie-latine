"""History of one sentence of a version: its Latin at each step where it changed, and the
working text, for the writers of the version."""

from dataclasses import dataclass

from accounts.models import User
from moderation.registry import can_view

from .diffs import word_diff
from .sources import SourceHistory
from .steps import carried, step_sentences


@dataclass
class Entry:
    text: str
    step: object  # a VersionStep, or None for the working text
    written_by: User | None
    chunks: list


def sentence_history(user, version, segment):
    """[Entry] of the Latin of a sentence, the latest first: the working text, then each step
    that changed it (a merge or a split of the source text carries the Latin along)."""
    history = SourceHistory(version.project.source_text)
    steps = [step for step in version.steps.order_by("number") if _visible(user, step, version)]
    versions_of_text = []
    for step in steps:
        texts = history.project(carried(step_sentences(step)), step.source_state)
        found = texts.get(segment.pk)
        text, writer = (found.text, found.written_by_id) if found else ("", None)
        if not versions_of_text or versions_of_text[-1][0] != text:
            versions_of_text.append((text, step, writer))
    working = version.segments.filter(segment=segment).first()
    working_text = working.text if working else ""
    if not versions_of_text or versions_of_text[-1][0] != working_text:
        writer = working.written_by_id if working else None
        versions_of_text.append((working_text, None, writer))
    writers = User.objects.in_bulk(
        {writer for _text, _step, writer in versions_of_text if writer} | {version.author_id}
    )
    entries, previous = [], ""
    for text, step, writer in versions_of_text:
        entries.append(
            Entry(text, step, writers.get(writer or version.author_id), word_diff(previous, text))
        )
        previous = text
    return entries[::-1]


def _visible(user, step, version):
    step.version = version
    return can_view(user, step)
