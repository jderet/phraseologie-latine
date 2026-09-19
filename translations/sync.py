"""Between a copy and its original, like a fork and its upstream repository.

A copy takes, sentence by sentence, what the original changed since the copy (or since the last
update); a copy proposes to the original the sentences where it differs. Only public steps of
the original are read."""

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext

from accounts.models import User
from moderation.registry import can_view
from moderation.services import save_with_revision

from .diffs import word_diff
from .models import TranslatedSegment, TranslationVersion, is_version_writer
from .services import save_translation
from .sources import SourceHistory
from .steps import carried, public_step, step_sentences


@dataclass
class UpstreamChange:
    segment: object
    number: int
    before: str
    after: str
    mine: str
    written_by: User | None
    chunks: list

    @property
    def is_clean(self):
        """The copy still has the Latin the original had: taking the change loses nothing."""
        return self.mine == self.before


def _texts(history, step):
    """{segment id: Carried} of a step, carried to the current source text."""
    return history.project(carried(step_sentences(step)), step.source_state)


def upstream(version):
    """(original step now public, base step) for a copy, or (None, None)."""
    if version.copied_from_id is None:
        return None, None
    base = version.synced_to or version.copied_from
    return public_step(base.version), base


def upstream_changes(user, version):
    """What the original changed, sentence by sentence, since the copy or the last update."""
    if not is_version_writer(user, version):
        raise PermissionDenied
    latest, base = upstream(version)
    if latest is None or latest.number <= base.number or not can_view(user, latest.version):
        return latest, []
    history = SourceHistory(version.project.source_text)
    before, after = _texts(history, base), _texts(history, latest)
    working = {item.segment_id: item.text for item in version.segments.current()}
    numbers = history.numbers_at()
    writers = User.objects.in_bulk(
        {item.written_by_id for item in after.values() if item.written_by_id}
        | {latest.version.author_id}
    )
    changes = []
    for segment in history.segments_at():
        old = before.get(segment.pk)
        new = after.get(segment.pk)
        old_text, new_text = (old.text if old else ""), (new.text if new else "")
        if old_text == new_text or not new_text:
            continue
        writer_id = (new.written_by_id if new else None) or latest.version.author_id
        changes.append(
            UpstreamChange(
                segment=segment,
                number=numbers[segment.pk],
                before=old_text,
                after=new_text,
                mine=working.get(segment.pk, ""),
                written_by=writers.get(writer_id),
                chunks=word_diff(old_text, new_text),
            )
        )
    return latest, changes


@transaction.atomic
def take_upstream(user, version, segment_ids):
    """Take the chosen changes of the original into the working text, in the name of whoever
    wrote them; the copy is then up to date with the latest public step of the original."""
    version = TranslationVersion.objects.select_for_update().get(pk=version.pk)
    latest, changes = upstream_changes(user, version)
    if latest is None:
        return 0
    taken = 0
    for change in changes:
        if change.segment.pk in segment_ids and change.after != change.mine:
            save_translation(
                version, change.segment, change.after, user, written_by=change.written_by
            )
            taken += 1
    version.synced_to = latest
    save_with_revision(version, user, comment=gettext("Mise à jour depuis l’originale"))
    return taken


def differences_with_original(user, version):
    """Sentences where the working text of a copy differs from the latest public step of its
    original, among the sentences of that step: [(segment, number, original, mine, chunks)]."""
    if not is_version_writer(user, version) or version.copied_from_id is None:
        raise PermissionDenied
    original = version.copied_from.version
    latest = public_step(original)
    if latest is None:
        return None, []
    history = SourceHistory(version.project.source_text)
    frozen = {segment_id: item.text for segment_id, item in carried(step_sentences(latest)).items()}
    working = {
        item.segment_id: item.text
        for item in TranslatedSegment.objects.current().filter(version=version)
    }
    rows = []
    for number, segment in enumerate(history.segments_at(latest.source_state), start=1):
        if segment.removed_in is not None:
            continue
        theirs, mine = frozen.get(segment.pk, ""), working.get(segment.pk, "")
        if mine and mine != theirs:
            rows.append((segment, number, theirs, mine, word_diff(theirs, mine)))
    return latest, rows
