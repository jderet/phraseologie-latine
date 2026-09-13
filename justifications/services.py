"""Justifying translation choices; every change is recorded as a revision."""

from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext

from corpus.models import Token
from corpus.search import corpus_version
from moderation.services import save_with_revision
from translations.permissions import can_translate

from .models import ATTESTED_STRENGTHS, Evidence, Justification, Strength

MAX_CITED_WORDS = 12


@dataclass
class EvidenceInput:
    """Evidence chosen in a form, before it is saved."""

    kind: str
    tokens: list = field(default_factory=list)
    work: object = None
    locator: str = ""
    note: str = ""


def corpus_evidence(value):
    """An attestation from the value sent by a form: word identifiers separated by commas."""
    ids = {int(part) for part in value.split(",") if part.strip().isdigit()}
    tokens = list(Token.objects.filter(pk__in=ids).select_related("passage__edition__work__author"))
    if (
        not ids
        or len(ids) > MAX_CITED_WORDS
        or len(tokens) != len(ids)
        or len({token.edition_id for token in tokens}) != 1
    ):
        raise ValidationError(
            gettext("Cette attestation n’est pas valide : refaites la recherche."),
            code="invalid_attestation",
        )
    return EvidenceInput(Evidence.Kind.CORPUS, sorted(tokens, key=lambda token: token.position))


def reference_evidence(work, locator, note=""):
    return EvidenceInput(work.kind, work=work, locator=locator, note=note)


def find_excerpt(text, excerpt, hint=None):
    """Position of the excerpt in the Latin sentence: the occurrence nearest the hint."""
    starts = [index for index in range(len(text)) if excerpt and text.startswith(excerpt, index)]
    if not starts:
        raise ValidationError(
            gettext("Ce passage ne figure pas dans la phrase latine : copiez-le tel quel."),
            code="excerpt_not_found",
        )
    if hint is None:
        return starts[0]
    return min(starts, key=lambda start: abs(start - hint))


def check_strength(strength, comment, evidences):
    """The evidence each strength requires."""
    kinds = {evidence.kind for evidence in evidences}
    if strength in ATTESTED_STRENGTHS and Evidence.Kind.CORPUS not in kinds:
        raise ValidationError(
            gettext("Cette force de preuve exige au moins une attestation du corpus."),
            code="attestation_required",
        )
    if strength == Strength.ANALOGY:
        if not comment.strip():
            raise ValidationError(
                gettext("Une justification par analogie exige un commentaire."),
                code="comment_required",
            )
        if not evidences:
            raise ValidationError(
                gettext("Une justification par analogie s’appuie sur au moins une preuve."),
                code="evidence_required",
            )
    if strength == Strength.NOT_FOUND and not evidences and not comment.strip():
        raise ValidationError(
            gettext("Expliquez ce choix par un commentaire ou par une preuve."),
            code="explanation_required",
        )


def active_evidences(justification):
    return list(justification.evidences.filter(is_withdrawn=False))


def _save_evidence(justification, evidence, author):
    obj = Evidence(
        justification=justification,
        kind=evidence.kind,
        passage=evidence.tokens[0].passage if evidence.tokens else None,
        work=evidence.work,
        locator=evidence.locator,
        note=evidence.note,
    )
    save_with_revision(obj, author, m2m={"tokens": evidence.tokens})
    return obj


@transaction.atomic
def create_justification(justification, author, evidences, hint=None):
    """Justify words of a translated sentence; only the author of the version may (Q44)."""
    translated = justification.translated_segment
    if not can_translate(author, translated.version):
        raise PermissionDenied
    justification.author = author
    justification.latin_start = find_excerpt(translated.text, justification.latin_excerpt, hint)
    check_strength(justification.strength, justification.comment, evidences)
    if justification.strength == Strength.NOT_FOUND:
        justification.corpus_version = corpus_version().label
    save_with_revision(justification, author)
    for evidence in evidences:
        _save_evidence(justification, evidence, author)
    return justification


@transaction.atomic
def update_justification(justification, author, hint=None):
    """Save a changed justification; choosing the words again takes it out of review."""
    if author.pk != justification.author_id:
        raise PermissionDenied
    previous = Justification.objects.select_for_update().get(pk=justification.pk)
    text = justification.translated_segment.text
    justification.latin_start = find_excerpt(text, justification.latin_excerpt, hint)
    check_strength(justification.strength, justification.comment, active_evidences(justification))
    if justification.strength != Strength.NOT_FOUND:
        justification.corpus_version = ""
    elif previous.strength != Strength.NOT_FOUND:
        justification.corpus_version = corpus_version().label
    return save_with_revision(justification, author)


@transaction.atomic
def add_evidences(justification, evidences, author):
    if author.pk != justification.author_id:
        raise PermissionDenied
    return [_save_evidence(justification, evidence, author) for evidence in evidences]


@transaction.atomic
def withdraw_evidence(evidence, author):
    """Withdraw a piece of evidence, if the justification still has what its strength needs."""
    justification = evidence.justification
    if author.pk != justification.author_id:
        raise PermissionDenied
    if evidence.is_withdrawn:
        return None
    remaining = [item for item in active_evidences(justification) if item.pk != evidence.pk]
    check_strength(justification.strength, justification.comment, remaining)
    evidence.is_withdrawn = True
    return save_with_revision(evidence, author, comment=gettext("Preuve retirée"))
