"""Reading notes: public comments on a group of words, written by any active account.

A reading note is a moderated content, counted toward the limits of new accounts; the reader
shows or hides the notes of the text.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext

from justifications.services import corpus_evidence
from moderation.services import save_with_revision

from .models import ReadingNote


@transaction.atomic
def create_reading_note(words, user, text):
    """A public note about words of the corpus, given by their identifiers."""
    if not (user.is_authenticated and user.is_active):
        raise PermissionDenied
    text = text.strip()
    if not text:
        raise ValidationError(gettext("Écrivez la note."), code="empty")
    evidence = corpus_evidence(words)
    note = ReadingNote(passage=evidence.tokens[0].passage, text=text, created_by=user)
    save_with_revision(note, user, m2m={"tokens": evidence.tokens})
    return note


def word_reading_notes(token):
    """The visible reading notes about a word."""
    return list(
        ReadingNote.objects.filter(tokens=token, is_hidden=False)
        .select_related("created_by")
        .order_by("created_at", "pk")
    )


@dataclass
class ReadingNoteMark:
    """A reading note drawn among the words of a page: a thin wavy line under its words."""

    note: ReadingNote
    words: list
    # Drawn closest to the word, under the lines of the phraseology, as the notebook.
    track: int = -1

    @property
    def key(self):
        return f"l_{self.note.pk}"

    @property
    def css(self):
        return "rn"


def page_reading_notes(passages, token_ids):
    """The visible reading notes beginning in the passages of a page, in the order of the text,
    each with its words on the page."""
    visible = ReadingNote.objects.filter(passage__in=passages, is_hidden=False).select_related(
        "created_by", "passage__edition__work"
    )
    notes = {note.pk: note for note in visible}
    rows = (
        ReadingNote.tokens.through.objects.filter(readingnote_id__in=list(notes))
        .order_by("token__position")
        .values_list("readingnote_id", "token_id", "token__position")
    )
    found, starts = defaultdict(list), {}
    for pk, token_id, position in rows:
        if token_id in token_ids:
            found[pk].append(token_id)
            starts.setdefault(pk, position)
    ordered = sorted(found, key=lambda pk: (starts[pk], pk))
    return [ReadingNoteMark(notes[pk], found[pk]) for pk in ordered]
