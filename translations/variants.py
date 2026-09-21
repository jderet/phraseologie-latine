"""Variants of a sentence: another Latin for one sentence of a translation.

A variant corrects the main text of its sentence, or another variant of it. A **proposal** asks
for its Latin to take the place of what it corrects; a variant kept **for reference** only
records another reading. Translators and editors adopt or refuse a proposal: adopting moves its
Latin into the main text, and what it replaced stays, for reference (choice of 21 September
2026).
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from activity.models import Verb
from activity.services import auto_follow, record
from moderation.registry import can_view
from moderation.services import save_with_revision

from .models import (
    Segment,
    SegmentVariant,
    TranslatedSegment,
    can_correct,
    is_translator,
    version_writer_ids,
)
from .services import normalize_sentence, save_translation

MAX_VARIANTS = 30


def can_add_variant(user, version):
    """Correctors, translators and editors add variants to the sentences of a translation they
    may see; while the correction is open, any active account may."""
    return (
        user.is_authenticated
        and user.is_active
        and not version.is_hidden
        and can_view(user, version)
        and can_correct(user, version.project)
    )


def can_edit_variant(user, variant):
    """Its author, while it waits for a decision, and the translators."""
    if not user.is_authenticated or not user.is_active:
        return False
    if is_translator(user, variant.version.project):
        return True
    return user.pk == variant.author_id and variant.decision == SegmentVariant.Decision.PENDING


def can_decide_variant(user, variant):
    """Translators and editors adopt or refuse a proposal that waits for a decision."""
    return (
        user.is_authenticated
        and user.is_active
        and variant.is_pending
        and is_translator(user, variant.version.project)
    )


def variants_for(user, version, segment):
    """The variants of one sentence the user may see, oldest first."""
    found = [
        variant
        for variant in version.variants.filter(segment=segment).select_related(
            "author", "version__project", "target"
        )
        if can_view(user, variant)
    ]
    for variant in found:
        variant.version = version
    return found


def variants_by_segment(user, version):
    """{segment id: [variant]} for the whole translation, oldest first."""
    found = {}
    for variant in version.variants.select_related("author", "target"):
        variant.version = version
        if can_view(user, variant):
            found.setdefault(variant.segment_id, []).append(variant)
    return found


def _check_sentence(version, segment):
    if (
        not Segment.objects.current()
        .filter(pk=segment.pk, source_text_id=version.project.source_text_id)
        .exists()
    ):
        raise ValueError("The sentence does not belong to the current text of the version.")


@transaction.atomic
def add_variant(variant, author):
    """Add a variant to one sentence, of the main text or of another variant."""
    version = variant.version
    if not can_add_variant(author, version):
        raise PermissionDenied
    _check_sentence(version, variant.segment)
    if variant.target_id is not None:
        target = SegmentVariant.objects.get(pk=variant.target_id)
        if target.version_id != version.pk or target.segment_id != variant.segment_id:
            raise ValidationError(
                gettext("Cette variante porte sur une autre phrase."), code="other_sentence"
            )
        if not can_view(author, target):
            raise PermissionDenied
    variant.text = normalize_sentence(variant.text)
    if not variant.text:
        raise ValidationError(gettext("Écrivez le latin de la variante."), code="empty")
    if variant.text == _current_text(version, variant):
        raise ValidationError(
            gettext("Cette variante répète le texte qu’elle corrige."), code="same"
        )
    if version.variants.filter(segment=variant.segment).count() >= MAX_VARIANTS:
        raise ValidationError(
            gettext("Cette phrase a déjà %(count)d variantes.") % {"count": MAX_VARIANTS},
            code="too_many",
        )
    variant.author = author
    save_with_revision(variant, author)
    auto_follow(author, version)
    record(
        author,
        Verb.VARIANT_ADDED,
        variant,
        recipients=version_writer_ids(version),
        mention_text=variant.comment,
    )
    return variant


def _current_text(version, variant):
    """The Latin the variant corrects: its target, or the main text of the sentence."""
    if variant.target_id is not None:
        return variant.target.text
    sentence = TranslatedSegment.objects.filter(
        version=version, segment=variant.segment
    ).first()
    return sentence.text if sentence is not None else ""


@transaction.atomic
def edit_variant(variant, user, text, comment, status):
    """Its author or a translator rewrites a variant."""
    variant = SegmentVariant.objects.select_for_update().get(pk=variant.pk)
    if not can_edit_variant(user, variant):
        raise PermissionDenied
    if status not in SegmentVariant.Status.values:
        raise ValueError("Unknown status.")
    text = normalize_sentence(text)
    if not text:
        raise ValidationError(gettext("Écrivez le latin de la variante."), code="empty")
    variant.text = text
    variant.comment = comment
    variant.status = status
    return save_with_revision(variant, user)


@transaction.atomic
def delete_variant(variant, user):
    """Its author, while it waits, or a translator takes a variant away; its corrections go
    back to what it corrected itself."""
    variant = SegmentVariant.objects.select_for_update().get(pk=variant.pk)
    if not can_edit_variant(user, variant):
        raise PermissionDenied
    variant.corrections.update(target=variant.target_id)
    variant.delete()


@transaction.atomic
def adopt_variant(variant, user):
    """Put the Latin of a proposal in the main text of its sentence.

    What it replaces stays: the main text becomes a variant kept for reference, at the name of
    whoever wrote it, and a variant the proposal corrected is kept for reference too. The
    corrections of the adopted proposal now correct the main text.
    """
    variant = (
        SegmentVariant.objects.select_for_update()
        .select_related("version__project")
        .get(pk=variant.pk)
    )
    if not can_decide_variant(user, variant):
        raise PermissionDenied
    version = variant.version
    _check_sentence(version, variant.segment)
    _keep_main_text(version, variant, user)
    save_translation(version, variant.segment, variant.text, user, written_by=variant.author)
    if variant.target is not None and variant.target.is_proposal:
        target = variant.target
        target.status = SegmentVariant.Status.REFERENCE
        save_with_revision(target, user, comment=gettext("Corrigée par une proposition adoptée"))
    variant.corrections.update(target=None)
    variant.decision = SegmentVariant.Decision.ADOPTED
    variant.decided_by = user
    variant.decided_at = timezone.now()
    save_with_revision(variant, user, comment=gettext("Adoptée"))
    record(
        user,
        Verb.VARIANT_ADOPTED,
        variant,
        recipients={variant.author_id} | version_writer_ids(version),
    )
    return variant


def _keep_main_text(version, variant, user):
    """Keep the main text of the sentence as a variant, for reference."""
    sentence = TranslatedSegment.objects.filter(version=version, segment=variant.segment).first()
    if sentence is None or not sentence.text:
        return None
    kept = SegmentVariant(
        version=version,
        segment=variant.segment,
        text=sentence.text,
        comment=gettext("Texte principal remplacé par une proposition."),
        status=SegmentVariant.Status.REFERENCE,
        author_id=sentence.written_by_id or version.author_id,
    )
    return save_with_revision(kept, user).content_object


@transaction.atomic
def refuse_variant(variant, user):
    """A refused proposal stays, for reference."""
    variant = (
        SegmentVariant.objects.select_for_update()
        .select_related("version__project")
        .get(pk=variant.pk)
    )
    if not can_decide_variant(user, variant):
        raise PermissionDenied
    variant.status = SegmentVariant.Status.REFERENCE
    variant.decision = SegmentVariant.Decision.REFUSED
    variant.decided_by = user
    variant.decided_at = timezone.now()
    save_with_revision(variant, user, comment=gettext("Refusée : gardée pour référence"))
    record(
        user,
        Verb.VARIANT_REFUSED,
        variant,
        recipients={variant.author_id} | version_writer_ids(variant.version),
    )
    return variant
