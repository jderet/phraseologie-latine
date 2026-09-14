"""Creating and completing phraseological units; every change is recorded as a revision."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext

from moderation.registry import can_view
from moderation.services import save_with_revision

from .models import Attestation, Sense, Unit, UnitRelation
from .permissions import can_edit_unit, can_withdraw_attestation


def _check_edit(user, unit):
    if not can_edit_unit(user, unit):
        raise PermissionDenied


@transaction.atomic
def create_unit(unit, author, definition, attestations):
    """A unit is created with three fields: reference form, a sense, an attestation (T3).

    ``attestations`` are corpus evidence inputs (``justifications.services.corpus_evidence``).
    The new unit is a draft, visible to its creator only.
    """
    if not definition.strip():
        raise ValidationError(gettext("Indiquez le sens de l’unité."), code="sense_required")
    if not attestations:
        raise ValidationError(
            gettext("Choisissez au moins une attestation dans le corpus."),
            code="attestation_required",
        )
    unit.created_by = author
    unit.status = Unit.Status.DRAFT
    save_with_revision(unit, author)
    sense = Sense(unit=unit, definition=definition)
    save_with_revision(sense, author)
    add_attestations(unit, attestations, author, sense=sense)
    return unit


@transaction.atomic
def update_unit(unit, user):
    _check_edit(user, unit)
    return save_with_revision(unit, user)


def _check_part(part, user):
    unit = part.unit
    _check_edit(user, unit)
    if isinstance(part, UnitRelation):
        target = part.target
        if target.pk == unit.pk or target.is_draft or not can_view(user, target):
            raise ValidationError(
                gettext("Choisissez une autre unité, proposée ou validée."), code="invalid_target"
            )


@transaction.atomic
def save_part(part, user):
    """Add or change a sense, an equivalent, a realization, a relation or a reference."""
    _check_part(part, user)
    return save_with_revision(part, user)


@transaction.atomic
def withdraw_part(part, user):
    """Withdraw a part of a unit; it stays in the history."""
    _check_edit(user, part.unit)
    if part.is_withdrawn:
        return None
    if isinstance(part, Sense) and not part.unit.senses.active().exclude(pk=part.pk).exists():
        raise ValidationError(gettext("Une unité garde au moins un sens."), code="last_sense")
    part.is_withdrawn = True
    return save_with_revision(part, user, comment=gettext("Retrait"))


@transaction.atomic
def add_attestations(
    unit, attestations, user, sense=None, realization=None, origin=Attestation.Origin.MANUAL
):
    """Attach corpus words to a unit; words already attested for it are skipped."""
    _check_edit(user, unit)
    for part in (sense, realization):
        if part is not None and part.unit_id != unit.pk:
            raise ValueError("The sense or the realization belongs to another unit.")
    existing = unit.attestations.active().exclude(status=Attestation.Status.REJECTED)
    known = {
        frozenset(token.pk for token in attestation.tokens.all())
        for attestation in existing.prefetch_related("tokens")
    }
    created = []
    for evidence in attestations:
        words = frozenset(token.pk for token in evidence.tokens)
        if words in known:
            continue
        attestation = Attestation(
            unit=unit,
            sense=sense,
            realization=realization,
            passage=evidence.tokens[0].passage,
            origin=origin,
            created_by=user,
        )
        save_with_revision(attestation, user, m2m={"tokens": evidence.tokens})
        known.add(words)
        created.append(attestation)
    return created


@transaction.atomic
def withdraw_attestation(attestation, user):
    if not can_withdraw_attestation(user, attestation):
        raise PermissionDenied
    others = attestation.unit.attestations.active().exclude(pk=attestation.pk)
    if not others.exclude(status=Attestation.Status.REJECTED).exists():
        raise ValidationError(
            gettext("Une unité garde au moins une attestation."), code="last_attestation"
        )
    attestation.is_withdrawn = True
    return save_with_revision(attestation, user, comment=gettext("Retrait"))
