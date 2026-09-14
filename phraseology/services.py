"""Creating, completing and validating phraseological units; every change is recorded."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from accounts.limits import is_limited
from accounts.roles import is_reviewer
from corpus.search import corpus_version, default_layer
from justifications.services import attach_evidences
from moderation.registry import can_view
from moderation.services import post_comment, save_with_revision

from .frequency import count_by_author, schema_matches
from .models import (
    Attestation,
    Candidate,
    Neologism,
    Sense,
    Unit,
    UnitFrequency,
    UnitRelation,
)
from .permissions import can_edit_neologism, can_edit_unit, can_withdraw_attestation


def _check_edit(user, unit):
    if not can_edit_unit(user, unit):
        raise PermissionDenied


# Frequency and completeness


def current_frequency(unit):
    """The computed frequency of the unit, if it was computed for its present schema."""
    frequency = UnitFrequency.objects.filter(unit=unit).first()
    return frequency if frequency is not None and frequency.schema == unit.schema else None


def refresh_frequency(unit):
    """Count the occurrences of the schema in the analysed corpus; None when it cannot."""
    if not unit.schema:
        UnitFrequency.objects.filter(unit=unit).delete()
        return None
    layer = default_layer()
    if layer is None:
        return None
    rows = count_by_author(schema_matches(unit.edges, layer))
    frequency, _created = UnitFrequency.objects.update_or_create(
        unit=unit,
        defaults={
            "schema": unit.schema,
            "total": sum(total for _author, total, _core in rows),
            "core_total": sum(core for _author, _total, core in rows),
            "by_author": [[author.pk, total, core] for author, total, core in rows],
            "corpus_version": corpus_version().label,
            "computed_at": timezone.now(),
        },
    )
    return frequency


def missing_fields(unit):
    """What a unit still lacks to be validated, which demands every field (Q15)."""
    missing = []
    if not unit.kind:
        missing.append(_("le type"))
    if not unit.schema:
        missing.append(_("le schéma"))
    elif current_frequency(unit) is None:
        missing.append(_("la fréquence, calculée pour le schéma actuel"))
    if not unit.construction:
        missing.append(_("la construction"))
    if not unit.register:
        missing.append(_("le registre"))
    senses = unit.senses.active().filter(is_hidden=False)
    shown = Q(equivalents__is_withdrawn=False, equivalents__is_hidden=False)
    if not senses.exists():
        missing.append(_("un sens"))
    elif senses.annotate(shown=Count("equivalents", filter=shown)).filter(shown=0).exists():
        missing.append(_("un équivalent pour chaque sens"))
    examples = unit.attestations.active().filter(
        is_hidden=False, is_example=True, status=Attestation.Status.VALIDATED
    )
    if not examples.exists():
        missing.append(_("un exemple choisi parmi les attestations validées"))
    if not unit.references.active().filter(is_hidden=False).exists():
        missing.append(_("un renvoi bibliographique"))
    return missing


def _fields(missing):
    return ", ".join(str(field) for field in missing)


def _incomplete(missing):
    return ValidationError(
        gettext("Il manque : %(fields)s.") % {"fields": _fields(missing)}, code="incomplete"
    )


def _check_still_complete(unit):
    """A validated unit stays complete (rule 3): a change that would empty a field is refused."""
    unit = Unit.objects.get(pk=unit.pk)
    if unit.status == Unit.Status.VALIDATED:
        missing = missing_fields(unit)
        if missing:
            raise ValidationError(
                gettext("Une fiche validée reste complète ; il lui manquerait : %(fields)s.")
                % {"fields": _fields(missing)},
                code="validated_incomplete",
            )


# Creating and completing


@transaction.atomic
def create_unit(unit, author, definition, attestations, origin=Attestation.Origin.MANUAL):
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
    add_attestations(unit, attestations, author, sense=sense, origin=origin)
    return unit


@transaction.atomic
def update_unit(unit, user):
    """Save a changed unit; a new schema has its frequency computed again."""
    _check_edit(user, unit)
    revision = save_with_revision(unit, user)
    if current_frequency(unit) is None:
        refresh_frequency(unit)
    _check_still_complete(unit)
    return revision


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
    revision = save_with_revision(part, user)
    _check_still_complete(part.unit)
    return revision


@transaction.atomic
def withdraw_part(part, user):
    """Withdraw a part of a unit; it stays in the history."""
    _check_edit(user, part.unit)
    if part.is_withdrawn:
        return None
    if isinstance(part, Sense) and not part.unit.senses.active().exclude(pk=part.pk).exists():
        raise ValidationError(gettext("Une unité garde au moins un sens."), code="last_sense")
    part.is_withdrawn = True
    revision = save_with_revision(part, user, comment=gettext("Retrait"))
    _check_still_complete(part.unit)
    return revision


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
    revision = save_with_revision(attestation, user, comment=gettext("Retrait"))
    _check_still_complete(attestation.unit)
    return revision


@transaction.atomic
def review_attestation(attestation, reviewer, status):
    """A reviewer validates or rejects an attestation; once checked, it is no longer automatic."""
    if status not in (Attestation.Status.VALIDATED, Attestation.Status.REJECTED):
        raise ValueError("An attestation is validated or rejected.")
    attestation = (
        Attestation.objects.select_for_update(of=("self",))
        .select_related("unit")
        .get(pk=attestation.pk)
    )
    if not is_reviewer(reviewer) or not can_view(reviewer, attestation):
        raise PermissionDenied
    if attestation.is_withdrawn or attestation.status == status:
        return None
    attestation.status = status
    if status == Attestation.Status.VALIDATED:
        attestation.level = Attestation.Level.VALIDATED
        comment = gettext("Attestation validée")
    else:
        attestation.is_example = False
        comment = gettext("Attestation rejetée")
    attestation.reviewed_by = reviewer
    attestation.reviewed_at = timezone.now()
    revision = save_with_revision(attestation, reviewer, comment=comment)
    _check_still_complete(attestation.unit)
    return revision


@transaction.atomic
def set_example(attestation, user, is_example):
    """Choose an attestation as an example shown at the top of the unit, or stop showing it."""
    _check_edit(user, attestation.unit)
    if is_example and attestation.status == Attestation.Status.REJECTED:
        raise ValidationError(
            gettext("Une attestation rejetée ne sert pas d’exemple."), code="rejected_example"
        )
    attestation.is_example = is_example
    revision = save_with_revision(attestation, user)
    _check_still_complete(attestation.unit)
    return revision


# Status


@transaction.atomic
def propose_unit(unit, user):
    """Its creator makes a draft public; any active account may then complete it."""
    unit = Unit.objects.select_for_update().get(pk=unit.pk)
    if not user.is_active or user.pk != unit.created_by_id:
        raise PermissionDenied
    if not unit.is_draft:
        return None
    attestations = unit.attestations.active().exclude(status=Attestation.Status.REJECTED)
    if not unit.senses.active().exists() or not attestations.exists():
        raise ValidationError(
            gettext("Une fiche proposée a au moins un sens et une attestation."),
            code="incomplete_draft",
        )
    unit.status = Unit.Status.PROPOSED
    return save_with_revision(unit, user, comment=gettext("Proposition"))


@transaction.atomic
def validate_unit(unit, reviewer):
    """A reviewer validates a proposed unit whose fields are all filled (rule 3)."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    unit = Unit.objects.select_for_update().get(pk=unit.pk)
    if unit.status != Unit.Status.PROPOSED:
        raise ValidationError(
            gettext("Seule une fiche proposée peut être validée."), code="not_proposed"
        )
    missing = missing_fields(unit)
    if missing:
        raise _incomplete(missing)
    unit.status = Unit.Status.VALIDATED
    unit.validated_by = reviewer
    unit.validated_at = timezone.now()
    return save_with_revision(unit, reviewer, comment=gettext("Validation"))


@transaction.atomic
def contest_unit(unit, user, argument):
    """Anyone may contest a public unit; the argument opens its discussion (Q52)."""
    unit = Unit.objects.select_for_update().get(pk=unit.pk)
    if unit.status not in (Unit.Status.PROPOSED, Unit.Status.VALIDATED) or unit.is_hidden:
        raise ValidationError(
            gettext("Cette fiche ne peut pas être contestée."), code="not_contestable"
        )
    post_comment(unit, user, argument)
    unit.status = Unit.Status.CONTESTED
    return save_with_revision(unit, user, comment=gettext("Contestation"))


@transaction.atomic
def resolve_contest(unit, reviewer, status, reason):
    """A reviewer validates the contested unit again, or sends it back to be reviewed."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    if status not in (Unit.Status.VALIDATED, Unit.Status.PROPOSED):
        raise ValueError("A contested unit is validated again or proposed again.")
    unit = Unit.objects.select_for_update().get(pk=unit.pk)
    if unit.status != Unit.Status.CONTESTED:
        raise ValidationError(gettext("Cette fiche n’est pas contestée."), code="not_contested")
    if status == Unit.Status.VALIDATED:
        missing = missing_fields(unit)
        if missing:
            raise _incomplete(missing)
        unit.validated_by = reviewer
        unit.validated_at = timezone.now()
    post_comment(unit, reviewer, reason)
    unit.status = status
    return save_with_revision(unit, reviewer, comment=gettext("Contestation levée"))


# Neologisms


def _check_neologism(user, neologism):
    if not can_edit_neologism(user, neologism):
        raise PermissionDenied


@transaction.atomic
def create_neologism(neologism, author, equivalent, evidences):
    """A neologism is public at once, with its justification and a first equivalent (T5)."""
    neologism.created_by = author
    neologism.status = Neologism.Status.PROPOSED
    save_with_revision(neologism, author)
    equivalent.neologism = neologism
    save_with_revision(equivalent, author)
    attach_evidences(evidences, author, neologism=neologism)
    return neologism


@transaction.atomic
def update_neologism(neologism, user):
    _check_neologism(user, neologism)
    return save_with_revision(neologism, user)


@transaction.atomic
def save_neologism_equivalent(equivalent, user):
    _check_neologism(user, equivalent.neologism)
    return save_with_revision(equivalent, user)


@transaction.atomic
def withdraw_neologism_equivalent(equivalent, user):
    neologism = equivalent.neologism
    _check_neologism(user, neologism)
    if equivalent.is_withdrawn:
        return None
    if not neologism.equivalents.active().exclude(pk=equivalent.pk).exists():
        raise ValidationError(
            gettext("Un néologisme garde au moins un équivalent."), code="last_equivalent"
        )
    equivalent.is_withdrawn = True
    return save_with_revision(equivalent, user, comment=gettext("Retrait"))


@transaction.atomic
def add_neologism_evidences(neologism, evidences, user):
    _check_neologism(user, neologism)
    return attach_evidences(evidences, user, neologism=neologism)


@transaction.atomic
def withdraw_neologism_evidence(evidence, user):
    if evidence.neologism is None:
        raise ValueError("The evidence does not support a neologism.")
    _check_neologism(user, evidence.neologism)
    if evidence.is_withdrawn:
        return None
    evidence.is_withdrawn = True
    return save_with_revision(evidence, user, comment=gettext("Preuve retirée"))


@transaction.atomic
def validate_neologism(neologism, reviewer):
    if not is_reviewer(reviewer):
        raise PermissionDenied
    neologism = Neologism.objects.select_for_update().get(pk=neologism.pk)
    if neologism.status == Neologism.Status.VALIDATED:
        return None
    neologism.status = Neologism.Status.VALIDATED
    neologism.validated_by = reviewer
    neologism.validated_at = timezone.now()
    return save_with_revision(neologism, reviewer, comment=gettext("Validation"))


# Candidates


def _decide(candidate, user, status, unit=None):
    candidate = Candidate.objects.select_for_update().get(pk=candidate.pk)
    if candidate.status != Candidate.Status.PENDING:
        raise ValidationError(gettext("Ce candidat a déjà été examiné."), code="decided")
    candidate.status = status
    candidate.unit = unit
    candidate.decided_by = user
    candidate.decided_at = timezone.now()
    candidate.save()
    return candidate


@transaction.atomic
def retain_candidate(candidate, user, unit):
    """Record that a candidate became a unit, or belongs to a unit with the same schema."""
    if not user.is_active or not can_view(user, unit):
        raise PermissionDenied
    return _decide(candidate, user, Candidate.Status.RETAINED, unit)


@transaction.atomic
def create_unit_from_candidate(candidate, user, unit, definition, attestations):
    """Make a unit of a candidate: it receives the schema of the candidate and its frequency."""
    unit.schema = candidate.schema
    create_unit(unit, user, definition, attestations, origin=Attestation.Origin.CANDIDATE)
    refresh_frequency(unit)
    retain_candidate(candidate, user, unit)
    return unit


@transaction.atomic
def reject_candidate(candidate, user):
    """Confirmed accounts and reviewers reject a candidate that makes no unit."""
    if not user.is_authenticated or not user.is_active or is_limited(user):
        raise PermissionDenied
    return _decide(candidate, user, Candidate.Status.REJECTED)


@transaction.atomic
def reopen_candidate(candidate, reviewer):
    """A reviewer puts a decided candidate back in the queue; a unit made from it stays."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    candidate = Candidate.objects.select_for_update().get(pk=candidate.pk)
    candidate.status = Candidate.Status.PENDING
    candidate.unit = None
    candidate.decided_by = None
    candidate.decided_at = None
    candidate.save()
    return candidate
