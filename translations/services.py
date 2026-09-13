"""Creating and changing translation contents; every change is recorded as a revision."""

import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from moderation.services import save_with_revision

from .models import Segment, TranslatedSegment, TranslationProject, TranslationVersion
from .segmentation import to_lines


def normalize_sentence(text):
    """A sentence on one line, with single spaces and composed characters (ā, not a + ¯)."""
    return " ".join(unicodedata.normalize("NFC", text or "").split())


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


def create_project(project, author):
    project.created_by = author
    save_with_revision(project, author)
    return project


def create_version(version, author):
    version.author = author
    version.state = TranslationVersion.State.DRAFT
    save_with_revision(version, author)
    return version


@transaction.atomic
def save_translation(version, segment, text, author):
    """Save the Latin of one sentence of a version; return None when nothing changed."""
    if author.pk != version.author_id:
        raise PermissionDenied
    if segment.source_text_id != version.project.source_text_id:
        raise ValueError("The sentence does not belong to the text of the version.")
    text = normalize_sentence(text)
    translated = TranslatedSegment.objects.filter(version=version, segment=segment).first()
    if translated is None:
        if not text:
            return None
        translated = TranslatedSegment(version=version, segment=segment)
    translated.text = text
    return save_with_revision(translated, author)


@transaction.atomic
def publish_version(version, user):
    """Make a draft public; a published version never goes back to draft."""
    version = TranslationVersion.objects.select_for_update().get(pk=version.pk)
    if user.pk != version.author_id:
        raise PermissionDenied
    if version.is_published:
        return None
    if not version.segments.exclude(text="").exists():
        raise ValidationError(
            gettext("Traduisez au moins une phrase avant de publier."), code="empty"
        )
    version.state = TranslationVersion.State.PUBLISHED
    version.published_at = timezone.now()
    return save_with_revision(version, user, comment=gettext("Publication"))


@transaction.atomic
def set_reference_version(project, version, user):
    """The creator of a project chooses its reference version among published ones (T6).

    ``version`` None removes the reference. Return None when nothing changed.
    """
    project = TranslationProject.objects.select_for_update().get(pk=project.pk)
    if user.pk != project.created_by_id:
        raise PermissionDenied
    if version is not None and (
        version.project_id != project.pk or not version.is_published or version.is_hidden
    ):
        raise ValidationError(
            gettext("La version de référence doit être une version publiée de ce projet."),
            code="invalid_reference",
        )
    project.reference_version = version
    return save_with_revision(project, user, comment=gettext("Choix de la version de référence"))
