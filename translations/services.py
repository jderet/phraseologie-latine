"""Creating and changing translation contents; every change is recorded as a revision."""

import unicodedata
from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext, ngettext

from moderation.services import save_with_revision

from .models import (
    ChangeProposal,
    ProposedSentence,
    Segment,
    SourceChange,
    SourceText,
    StepSentence,
    TranslatedSegment,
    TranslationProject,
    TranslationVersion,
    VersionStep,
)
from .permissions import can_change_source, can_copy, can_propose
from .segmentation import MAX_SENTENCE_LENGTH, MAX_SENTENCES, to_lines
from .sources import (
    EDIT,
    INSERT,
    MERGE,
    SPLIT,
    Carried,
    Line,
    SourceHistory,
    apply_operation,
    carry,
    is_active,
)
from .steps import (
    latest_step,
    pending_changes,
    public_step,
    sentences_to_freeze,
    step_sentences,
    waiting_justifications,
)


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
            position=number,
            order=number,
            text=sentence.text,
            starts_paragraph=sentence.starts_paragraph,
        )
        for number, sentence in enumerate(sentences, start=1)
    )
    return source_text


def normalize_operation(operation):
    """An operation on the sentences of a text, with its texts normalized (see
    ``sources.apply_operation``); raise ValueError for an unknown operation."""
    kind = operation.get("kind")
    if kind == INSERT:
        sentences = [
            {
                "text": normalize_sentence(item["text"]),
                "starts_paragraph": bool(item.get("starts_paragraph")),
            }
            for item in operation["sentences"]
        ]
        return {
            "kind": kind,
            "before": int(operation["before"]),
            "sentences": [item for item in sentences if item["text"]],
        }
    if kind == EDIT:
        return {
            "kind": kind,
            "index": int(operation["index"]),
            "text": normalize_sentence(operation["text"]),
            "starts_paragraph": bool(operation.get("starts_paragraph")),
        }
    if kind == MERGE:
        return {"kind": kind, "index": int(operation["index"])}
    if kind == SPLIT:
        parts = [normalize_sentence(part) for part in operation["parts"]]
        return {"kind": kind, "index": int(operation["index"]), "parts": [p for p in parts if p]}
    raise ValueError(f"Unknown operation: {kind!r}")


def check_sentence_limits(lines):
    """A changed text keeps within the limits of an added one."""
    if len(lines) > MAX_SENTENCES:
        raise ValidationError(
            ngettext(
                "Un texte compte au plus %(limit)d phrase.",
                "Un texte compte au plus %(limit)d phrases.",
                MAX_SENTENCES,
            )
            % {"limit": MAX_SENTENCES},
            code="too_long",
        )
    if any(len(line.text) > MAX_SENTENCE_LENGTH for line in lines):
        raise ValidationError(
            gettext("Une phrase compte au plus %(limit)d caractères.")
            % {"limit": MAX_SENTENCE_LENGTH},
            code="sentence_too_long",
        )


def describe_operation(operation, count):
    """A short description of an operation on a text of ``count`` sentences, by number."""
    kind = operation["kind"]
    if kind == INSERT:
        added, before = len(operation["sentences"]), operation["before"]
        if before == 0:
            text = ngettext(
                "%(count)d phrase ajoutée au début",
                "%(count)d phrases ajoutées au début",
                added,
            )
        elif before >= count:
            text = ngettext(
                "%(count)d phrase ajoutée à la fin", "%(count)d phrases ajoutées à la fin", added
            )
        else:
            text = ngettext(
                "%(count)d phrase ajoutée après la phrase %(number)d",
                "%(count)d phrases ajoutées après la phrase %(number)d",
                added,
            )
        return text % {"count": added, "number": before}
    number = operation["index"] + 1
    if kind == EDIT:
        return gettext("Phrase %(number)d modifiée") % {"number": number}
    if kind == MERGE:
        return gettext("Phrases %(number)d et %(next)d fusionnées") % {
            "number": number,
            "next": number + 1,
        }
    return gettext("Phrase %(number)d scindée en %(count)d") % {
        "number": number,
        "count": len(operation["parts"]),
    }


@transaction.atomic
def change_source_text(source, operation, user):
    """Add, edit, merge or split sentences of a source text; see ``sources.apply_operation``.

    Only whoever added the text, or a reviewer, may. Return the ``SourceChange``.
    """
    source = SourceText.objects.select_for_update().get(pk=source.pk)
    if not can_change_source(user, source):
        raise PermissionDenied
    return apply_source_operation(source, operation, author=user)


def apply_source_operation(source, operation, author, adopted_by=None):
    """Record one change of the sentences of a locked source text; the caller checks rights.

    The removed sentences stay for the steps that froze them. In the working text of every
    version of the text, the first new sentence receives their Latin (``sources.carry``);
    each version shows it at its next step.
    """
    operation = normalize_operation(operation)
    history = SourceHistory(source)
    current = history.segments_at()
    applied = apply_operation(
        [Line(segment.text, segment.starts_paragraph) for segment in current], operation
    )
    check_sentence_limits(applied.lines)
    number = source.state + 1
    removed = current[applied.start : applied.start + applied.removed]
    added = [
        Segment(
            source_text=source,
            text=line.text,
            starts_paragraph=line.starts_paragraph,
            added_in=number,
        )
        for line in applied.added
    ]
    for segment in removed:
        segment.removed_in = number

    # New sentences go where they replace the removed ones, or before the sentence they
    # precede; positions and numbers are then given again to the whole text.
    ordered = list(history.segments)
    if removed:
        at = ordered.index(removed[-1]) + 1
    elif applied.start < len(current):
        at = ordered.index(current[applied.start])
    else:
        at = len(ordered)
    ordered[at:at] = added
    shown = 0
    for position, segment in enumerate(ordered, start=1):
        segment.position = position
        if segment.removed_in is None:
            shown += 1
            segment.order = shown
        else:
            segment.order = None
    Segment.objects.bulk_update(
        [segment for segment in ordered if segment.pk], ["position", "order", "removed_in"]
    )
    Segment.objects.bulk_create(added)

    change = SourceChange.objects.create(
        source_text=source,
        number=number,
        kind=operation["kind"],
        author=author,
        adopted_by=adopted_by,
    )
    source.state = number
    source.text = to_lines(applied.lines)
    editor = adopted_by or author
    save_with_revision(source, editor, comment=describe_operation(operation, len(current)))
    if removed:
        _carry_working_texts([segment.pk for segment in removed], added[0], editor)
    return change


def _carry_working_texts(removed_ids, carrier, editor):
    """Give the new sentence the Latin of the removed ones, in every version that had some."""
    rows = defaultdict(dict)
    for translated in TranslatedSegment.objects.filter(segment_id__in=removed_ids).select_related(
        "version"
    ):
        rows[translated.version_id][translated.segment_id] = translated
    for by_segment in rows.values():
        parts = [by_segment.get(segment_id) for segment_id in removed_ids]
        latin = carry([Carried(part.text, part.written_by_id) if part else None for part in parts])
        if latin is None:
            continue
        translated = TranslatedSegment(
            version=next(iter(by_segment.values())).version,
            segment=carrier,
            text=latin.text,
            written_by_id=latin.written_by_id,
        )
        save_with_revision(translated, editor, comment=gettext("Texte source changé"))


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
    # Checked in the database: the sentence may have been removed since it was loaded.
    if (
        not Segment.objects.current()
        .filter(pk=segment.pk, source_text_id=version.project.source_text_id)
        .exists()
    ):
        raise ValueError("The sentence does not belong to the current text of the version.")
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
    for segment, text in sorted(texts.items(), key=lambda item: item[0].position):
        if segment.source_text_id != version.project.source_text_id or not is_active(
            segment, step.source_state
        ):
            raise ValueError("The sentence does not belong to the text of the step.")
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
    if accept and proposed.segment.removed_in is not None:
        raise ValidationError(
            gettext(
                "La phrase source a changé depuis cette proposition : refusez cette phrase, ou "
                "recopiez son latin dans votre texte de travail."
            ),
            code="source_changed",
        )
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
    wrote it, until the new author rewrites it; justifications are not copied. The Latin of
    the step is carried to the current source text.
    """
    source = step.version
    if not can_copy(author, step):
        raise PermissionDenied
    version.project = source.project
    version.copied_from = step
    create_version(version, author)
    history = SourceHistory(_lock_source(version))
    frozen = {
        segment_id: Carried(sentence.text, sentence.written_by_id or source.author_id)
        for segment_id, sentence in step_sentences(step).items()
    }
    for segment_id, sentence in history.project(frozen, step.source_state).items():
        if not sentence.text:
            continue
        # A merge of sentences by several writers is credited to the author of the version.
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
    _record_step(version, author, message, history.source_text)
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
    if not version.segments.current().exclude(text="").exists():
        raise ValidationError(
            gettext("Traduisez au moins une phrase avant de publier."), code="empty"
        )
    version.state = TranslationVersion.State.PUBLISHED
    version.published_at = timezone.now()
    version.shows_draft_steps = show_draft_steps
    revision = save_with_revision(version, user, comment=gettext("Publication"))
    # Publishing always creates a step, the first one the public may see.
    message = normalize_sentence(message) or gettext("Publication")
    _record_step(version, user, message)
    return revision


def _lock_source(version):
    """The source text of a version, locked: its sentences do not change until the commit."""
    return SourceText.objects.select_for_update().get(pk=version.project.source_text_id)


def _record_step(version, author, message, source=None):
    """Freeze the working text and the current state of the source text."""
    source = source or _lock_source(version)
    rows = sentences_to_freeze(version, latest_step(version))
    last = version.steps.aggregate(last=Max("number"))["last"] or 0
    step = VersionStep(
        version=version,
        number=last + 1,
        message=message,
        author=author,
        during_draft=version.is_draft,
        source_state=source.state,
    )
    save_with_revision(step, author)
    StepSentence.objects.bulk_create(
        StepSentence(
            step=step,
            segment_id=item.segment_id,
            text=item.text,
            written_by_id=item.written_by_id,
        )
        for item in rows
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
    source = _lock_source(version)
    previous = latest_step(version)
    source_changed = previous is not None and source.state > previous.source_state
    if (
        not source_changed
        and not pending_changes(version, SourceHistory(source))
        and not waiting_justifications(version).exists()
    ):
        raise ValidationError(
            gettext("Rien n’a changé depuis la dernière étape."), code="unchanged"
        )
    return _record_step(version, author, message, source)


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
