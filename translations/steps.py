"""The text of a version at each step, and what changed in the working text since the last one.

A step stores only the sentences it changed: the text of a sentence at a step is the one of
the latest step, up to it, that changed the sentence.
"""

from dataclasses import dataclass

from .models import Segment, StepSentence, is_version_author


@dataclass(frozen=True)
class Change:
    """A sentence whose working text differs from the latest step."""

    segment: Segment
    before: str
    after: str
    written_by_id: int | None


def step_sentences(step):
    """Each sentence as the step froze it: {segment id: StepSentence, with its step loaded}."""
    rows = (
        StepSentence.objects.filter(step__version_id=step.version_id, step__number__lte=step.number)
        .select_related("step", "written_by")
        .order_by("step__number")
    )
    return {row.segment_id: row for row in rows}


def latest_step(version):
    return version.steps.order_by("-number").first()


def public_step(version):
    """The step the public sees: the latest public step of the version, or None."""
    return version.steps.public().order_by("-number").first()


def shown_sentences(user, version, step=None):
    """(step, {segment id: sentence}) of the text the user sees; a sentence has ``text`` and
    ``written_by``.

    With no step asked, the author sees the working text (the step is then None) and others
    the latest public step, if any.
    """
    if step is None and is_version_author(user, version):
        return None, {item.segment_id: item for item in version.segments.all()}
    if step is None:
        step = public_step(version)
    if step is None:
        return None, {}
    return step, step_sentences(step)


def shown_text(user, translated):
    """The Latin of a translated sentence as the user sees it (see ``shown_sentences``)."""
    version = translated.version
    if is_version_author(user, version):
        return translated.text
    step = public_step(version)
    return sentence_at(step, translated.segment_id) if step else ""


def sentence_at(step, segment_id):
    """The Latin of a sentence as the step froze it; empty if it had none."""
    row = (
        StepSentence.objects.filter(
            step__version_id=step.version_id,
            step__number__lte=step.number,
            segment_id=segment_id,
        )
        .order_by("-step__number")
        .first()
    )
    return row.text if row else ""


def pending_changes(version):
    """Sentences whose working text differs from the latest step, in the order of the text."""
    step = latest_step(version)
    frozen = step_sentences(step) if step else {}
    changes = []
    for item in version.segments.select_related("segment").order_by("segment__order"):
        before = frozen[item.segment_id].text if item.segment_id in frozen else ""
        if item.text != before:
            changes.append(Change(item.segment, before, item.text, item.written_by_id))
    return changes
