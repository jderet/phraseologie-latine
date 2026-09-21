"""Put the working text of a translation back to the state of one of its steps."""

from django.core.exceptions import PermissionDenied
from django.db import transaction

from accounts.models import User

from .diffs import word_diff
from .models import is_version_writer
from .services import save_translation
from .sources import SourceHistory
from .steps import carried, step_sentences


def _texts(history, step):
    """{segment id: Carried} of a step, carried to the current source text."""
    return history.project(carried(step_sentences(step)), step.source_state)


def restore_preview(version, step):
    """Sentences whose working text differs from the Latin of a step, carried to the current
    source text: [(segment, number, current, restored, written_by_id, chunks)]."""
    history = SourceHistory(version.project.source_text)
    frozen = _texts(history, step)
    working = {item.segment_id: item.text for item in version.segments.current()}
    rows = []
    for number, segment in enumerate(history.segments_at(), start=1):
        item = frozen.get(segment.pk)
        restored = item.text if item else ""
        current = working.get(segment.pk, "")
        if restored != current:
            writer = item.written_by_id if item else None
            rows.append((segment, number, current, restored, writer, word_diff(current, restored)))
    return rows


@transaction.atomic
def restore_step(user, version, step):
    """Put the whole working text back to the state of a step; nothing is erased from the
    history, and the public sees the change only at the next step."""
    if not is_version_writer(user, version):
        raise PermissionDenied
    rows = restore_preview(version, step)
    writers = User.objects.in_bulk({writer for *_rest, writer, _c in rows if writer})
    for segment, _number, _current, restored, writer, _chunks in rows:
        save_translation(version, segment, restored, user, written_by=writers.get(writer))
    return len(rows)
