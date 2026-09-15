"""Creating and changing translation contents; every change is recorded as a revision."""

import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext

from moderation.services import save_with_revision

from .models import (
    ChangeProposal,
    ProposedSentence,
    Segment,
    StepSentence,
    TranslatedSegment,
    TranslationProject,
    TranslationVersion,
    VersionStep,
)
from .permissions import can_copy, can_propose
from .segmentation import to_lines
from .steps import pending_changes, public_step, step_sentences, waiting_justifications


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
def save_translation(version, segment, text, author, written_by=None):
    """Save the Latin of one sentence of a version; return None when nothing changed.

    ``written_by`` credits someone else with the new Latin: the author of an accepted proposal.
    """
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
    if translated.text != text:
        # A rewritten sentence belongs to whoever wrote the new Latin.
        credited = written_by is not None and written_by.pk != version.author_id
        translated.written_by = written_by if credited else None
    translated.text = text
    return save_with_revision(translated, author)


@transaction.atomic
def create_proposal(proposal, author, texts):
    """Propose changes to the published version of someone else, like a pull request.

    ``texts`` maps sentences of the source text to Latin; only those that differ from the
    latest public step are kept. The author of the version decides on each (Q36).
    """
    version = proposal.version
    step = public_step(version)
    if step is None or not can_propose(author, version):
        raise PermissionDenied
    frozen = step_sentences(step)
    changed = []
    for segment, text in sorted(texts.items(), key=lambda item: item[0].order):
        if segment.source_text_id != version.project.source_text_id:
            raise ValueError("The sentence does not belong to the text of the version.")
        text = normalize_sentence(text)
        base = frozen[segment.pk].text if segment.pk in frozen else ""
        if text != base:
            changed.append((segment, base, text))
    if not changed:
        raise ValidationError(
            gettext("Changez au moins une phrase avant d’envoyer la proposition."),
            code="unchanged",
        )
    proposal.author = author
    proposal.base_step = step
    save_with_revision(proposal, author)
    for segment, base, text in changed:
        proposed = ProposedSentence(proposal=proposal, segment=segment, base_text=base, text=text)
        save_with_revision(proposed, author)
    return proposal


@transaction.atomic
def decide_sentence(proposed, user, accept):
    """The author of the version accepts or refuses a proposed sentence (Q36).

    An accepted sentence replaces the working text, in the name of whoever proposed it; the
    public sees it at the next step. The proposal closes once every sentence is decided.
    """
    proposal = ChangeProposal.objects.select_for_update().get(pk=proposed.proposal_id)
    version = proposal.version
    if user.pk != version.author_id:
        raise PermissionDenied
    if not proposal.is_open:
        raise ValidationError(gettext("Cette proposition est close."), code="closed")
    proposed = ProposedSentence.objects.select_for_update().get(pk=proposed.pk)
    if not proposed.is_pending:
        raise ValidationError(gettext("Cette phrase a déjà été examinée."), code="decided")
    if accept:
        save_translation(version, proposed.segment, proposed.text, user, written_by=proposal.author)
        proposed.decision = ProposedSentence.Decision.ACCEPTED
    else:
        proposed.decision = ProposedSentence.Decision.REFUSED
    proposed.decided_at = timezone.now()
    save_with_revision(proposed, user, comment=proposed.get_decision_display())
    if not proposal.sentences.filter(decision=ProposedSentence.Decision.PENDING).exists():
        proposal.status = ChangeProposal.Status.CLOSED
        proposal.closed_at = timezone.now()
        save_with_revision(proposal, user, comment=gettext("Proposition close"))
    return proposed


@transaction.atomic
def withdraw_proposal(proposal, user):
    proposal = ChangeProposal.objects.select_for_update().get(pk=proposal.pk)
    if user.pk != proposal.author_id:
        raise PermissionDenied
    if not proposal.is_open:
        raise ValidationError(gettext("Cette proposition est close."), code="closed")
    proposal.status = ChangeProposal.Status.WITHDRAWN
    proposal.closed_at = timezone.now()
    return save_with_revision(proposal, user, comment=gettext("Proposition retirée"))


@transaction.atomic
def copy_version(step, version, author):
    """Start one's own draft version from a public step of a published version, like a fork.

    ``version`` carries the declared style. Each copied sentence stays credited to whoever
    wrote it, until the new author rewrites it; justifications are not copied.
    """
    source = step.version
    if not can_copy(author, step):
        raise PermissionDenied
    version.project = source.project
    version.copied_from = step
    create_version(version, author)
    for segment_id, sentence in step_sentences(step).items():
        if not sentence.text:
            continue
        writer_id = sentence.written_by_id or source.author_id
        translated = TranslatedSegment(
            version=version,
            segment_id=segment_id,
            text=sentence.text,
            written_by_id=None if writer_id == author.pk else writer_id,
        )
        save_with_revision(translated, author)
    message = gettext("Copie de la version de %(author)s, étape %(number)d") % {
        "author": source.author.public_name,
        "number": step.number,
    }
    _record_step(version, author, message, pending_changes(version))
    return version


@transaction.atomic
def publish_version(version, user, message="", show_draft_steps=False):
    """Make a draft public; a published version never goes back to draft.

    Publishing creates a step, with ``message`` or « Publication ». The author chooses once
    and for all whether the steps of the draft are shown.
    """
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
    version.shows_draft_steps = show_draft_steps
    revision = save_with_revision(version, user, comment=gettext("Publication"))
    # Publishing always creates a step, the first one the public may see.
    message = normalize_sentence(message) or gettext("Publication")
    _record_step(version, user, message, pending_changes(version))
    return revision


def _record_step(version, author, message, changes):
    last = version.steps.aggregate(last=Max("number"))["last"] or 0
    step = VersionStep(
        version=version,
        number=last + 1,
        message=message,
        author=author,
        during_draft=version.is_draft,
    )
    save_with_revision(step, author)
    StepSentence.objects.bulk_create(
        StepSentence(
            step=step,
            segment=change.segment,
            text=change.after,
            written_by_id=change.written_by_id,
        )
        for change in changes
    )
    waiting_justifications(version).update(step=step)
    return step


@transaction.atomic
def create_step(version, author, message):
    """Freeze the working text of a version with a message, like a Git commit.

    Only the author of the version may; the public then sees this step, and the justifications
    written since the previous one.
    """
    version = TranslationVersion.objects.select_for_update().get(pk=version.pk)
    if author.pk != version.author_id:
        raise PermissionDenied
    message = normalize_sentence(message)
    if not message:
        raise ValidationError(
            gettext("Écrivez un message : ce qui a changé depuis l’étape précédente."),
            code="no_message",
        )
    changes = pending_changes(version)
    if not changes and not waiting_justifications(version).exists():
        raise ValidationError(
            gettext("Rien n’a changé depuis la dernière étape."), code="unchanged"
        )
    return _record_step(version, author, message, changes)


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
