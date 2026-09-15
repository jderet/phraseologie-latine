"""The text of a version at each step, and what changed in the working text since the last one.

A step stores only the sentences it changed: the text of a sentence at a step is the one of
the latest step, up to it, that changed the sentence. A step also freezes the state of the
source text (``translations.sources``): its sentences are those of that state.
"""

from collections import Counter
from dataclasses import dataclass

from django.apps import apps
from django.db.models import Q
from django.utils.translation import gettext, ngettext

from .diffs import word_diff
from .models import Segment, StepSentence, TranslatedSegment, is_version_author
from .sources import EDIT, INSERT, MERGE, SPLIT, Carried, SourceHistory


@dataclass(frozen=True)
class Change:
    """A sentence whose working text differs from the latest step."""

    segment: Segment
    before: str
    after: str
    written_by_id: int | None


def step_sentences(step):
    """Each sentence of the text the step froze: {segment id: StepSentence, with its step}."""
    state = step.source_state
    rows = (
        StepSentence.objects.filter(
            step__version_id=step.version_id,
            step__number__lte=step.number,
            segment__added_in__lte=state,
        )
        .filter(Q(segment__removed_in__isnull=True) | Q(segment__removed_in__gt=state))
        .select_related("step", "written_by")
        .order_by("step__number")
    )
    return {row.segment_id: row for row in rows}


def carried(sentences):
    """{segment id: Carried} from sentences that have ``text`` and ``written_by_id``."""
    return {
        segment_id: Carried(sentence.text, sentence.written_by_id)
        for segment_id, sentence in sentences.items()
    }


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
        return None, {item.segment_id: item for item in version.segments.current()}
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


def working_translation(translated):
    """The row of the working text that now carries the Latin of a translated sentence.

    It is the row itself unless the source sentence has changed since; None if the sentence
    that carries it has no Latin yet.
    """
    segment = translated.segment.latest
    if segment.pk == translated.segment_id:
        return translated
    return TranslatedSegment.objects.filter(
        version_id=translated.version_id, segment=segment
    ).first()


def waiting_justifications(version):
    """Justifications of the version that no step has brought out yet."""
    # The justifications application depends on this one: its model is looked up by name.
    justification = apps.get_model("justifications", "Justification")
    return justification.objects.filter(translated_segment__version=version, step__isnull=True)


def pending_changes(version, history=None):
    """Sentences whose working text differs from the latest step, in the order of the text.

    The Latin of the step is first carried to the current source text: a sentence only
    edited, split or merged in the source text does not count as changed.
    """
    history = history or SourceHistory(version.project.source_text)
    step = latest_step(version)
    before = history.project(carried(step_sentences(step)), step.source_state) if step else {}
    working = {item.segment_id: item for item in version.segments.current()}
    changes = []
    for segment in history.segments_at():
        item, old = working.get(segment.pk), before.get(segment.pk)
        old_text, new_text = (old.text if old else ""), (item.text if item else "")
        if new_text != old_text:
            changes.append(
                Change(segment, old_text, new_text, item.written_by_id if item else None)
            )
    return changes


@dataclass(frozen=True)
class Comparison:
    """What changed from one text of a version to a later one.

    ``source_changes`` are the changes of the source text in between (``sources.Described``);
    ``sentences``, the Latin sentences that changed, as dicts with ``segment``, ``number``,
    ``before``, ``after`` and ``chunks`` (the word diff).
    """

    source_changes: list
    sentences: list

    @property
    def latin_summary(self):
        count = len(self.sentences)
        if not count:
            return gettext("latin inchangé")
        summary = ngettext(
            "%(count)d phrase traduite changée", "%(count)d phrases traduites changées", count
        ) % {"count": count}
        erased = sum(1 for row in self.sentences if not row["after"])
        if erased:
            summary += " " + ngettext(
                "(dont %(count)d effacée)", "(dont %(count)d effacées)", erased
            ) % {"count": erased}
        return summary

    @property
    def source_summary(self):
        kinds = Counter(item.kind for item in self.source_changes)
        added = sum(len(item.added) for item in self.source_changes if item.kind == INSERT)
        parts = []
        if added:
            parts.append(
                ngettext("%(count)d phrase ajoutée", "%(count)d phrases ajoutées", added)
                % {"count": added}
            )
        if kinds[EDIT]:
            parts.append(
                ngettext("%(count)d phrase modifiée", "%(count)d phrases modifiées", kinds[EDIT])
                % {"count": kinds[EDIT]}
            )
        if kinds[MERGE]:
            parts.append(
                ngettext("%(count)d fusion", "%(count)d fusions", kinds[MERGE])
                % {"count": kinds[MERGE]}
            )
        if kinds[SPLIT]:
            parts.append(
                ngettext("%(count)d scission", "%(count)d scissions", kinds[SPLIT])
                % {"count": kinds[SPLIT]}
            )
        return ", ".join(parts)


def compare(history, before, before_state, after, after_state):
    """Compare two texts of a version, {segment id: object with ``text``}, at their states of
    the source text (``before_state`` no later than ``after_state``).

    The Latin of the earlier text is first carried to the later source text: a sentence that
    only followed an edit, split or merge of the source text does not count as changed.
    """
    earlier = history.project(before, before_state, after_state)
    sentences = []
    for number, segment in enumerate(history.segments_at(after_state), start=1):
        old, new = earlier.get(segment.pk), after.get(segment.pk)
        old, new = (old.text if old else ""), (new.text if new else "")
        if old != new:
            sentences.append(
                {
                    "segment": segment,
                    "number": number,
                    "before": old,
                    "after": new,
                    "chunks": word_diff(old, new),
                }
            )
    return Comparison(history.describe(before_state, after_state), sentences)


def step_history(version, steps, history=None):
    """Each of ``steps``, with what it changed since the previous one of them.

    ``steps`` are the steps the user may see, in increasing number: a step is compared with the
    previous visible one, so that a private step of the draft never shows through. The text of
    every step is rebuilt in one pass over the sentences of the version.
    """
    history = history or SourceHistory(version.project.source_text)
    rows = list(
        StepSentence.objects.filter(step__version_id=version.pk)
        .order_by("step__number")
        .values_list("step__number", "segment_id", "text")
    )
    frozen, position, previous, result = {}, 0, None, []
    for step in steps:
        while position < len(rows) and rows[position][0] <= step.number:
            _number, segment_id, text = rows[position]
            frozen[segment_id] = Carried(text)
            position += 1
        snapshot = dict(frozen)
        if previous is None:
            comparison = compare(history, {}, step.source_state, snapshot, step.source_state)
        else:
            base, base_texts = previous
            comparison = compare(
                history, base_texts, base.source_state, snapshot, step.source_state
            )
        result.append((step, comparison))
        previous = (step, snapshot)
    return result


def sentences_to_freeze(version, step):
    """Rows of the working text a new step stores: those that differ from the text ``step``
    froze for the same sentence. A sentence new in the source text has no text there yet."""
    frozen = step_sentences(step) if step else {}
    return [
        item
        for item in version.segments.current()
        if item.text != (frozen[item.segment_id].text if item.segment_id in frozen else "")
    ]
