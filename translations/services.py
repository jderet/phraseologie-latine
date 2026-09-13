"""Creating and changing translation contents; every change is recorded as a revision."""

from django.db import transaction

from moderation.services import save_with_revision

from .models import Segment
from .segmentation import to_lines


@transaction.atomic
def create_source_text(source_text, author, sentences):
    """Save a new source text with its sentences, as checked by the person who adds it."""
    source_text.added_by = author
    source_text.text = to_lines(sentences)
    save_with_revision(source_text, author)
    Segment.objects.bulk_create(
        Segment(
            source_text=source_text,
            order=number,
            text=sentence.text,
            starts_paragraph=sentence.starts_paragraph,
        )
        for number, sentence in enumerate(sentences, start=1)
    )
    return source_text
