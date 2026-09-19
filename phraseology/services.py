"""Creating, completing and validating phraseological units; every change is recorded."""

from collections import defaultdict
from contextlib import suppress

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import QueryDict
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from accounts.limits import is_limited
from accounts.roles import is_reviewer
from corpus.forms import bound_search_form, search_query
from corpus.models import Token
from corpus.search import corpus_version, default_layer
from corpus.timeouts import TimeLimit
from justifications.services import attach_evidences
from moderation.registry import can_view
from moderation.services import post_comment, save_with_revision

from .frequency import count_by_author, occurrence_words, schema_matches
from .models import (
    AbstractWord,
    Attestation,
    AttestationDoubt,
    Candidate,
    Neologism,
    Sense,
    Unit,
    UnitFrequency,
    UnitRelation,
    UnitSurvey,
)
from .permissions import (
    can_edit_abstract_word,
    can_edit_neologism,
    can_edit_unit,
    can_withdraw_attestation,
)
from .schema import format_schema, writes_case
from .spotting import refresh_unit_forms


def _check_edit(user, unit):
    if not can_edit_unit(user, unit):
        raise PermissionDenied


# Frequency and completeness


def current_frequency(unit):
    """The computed frequency of the unit, if it was computed for its present schema."""
    frequency = UnitFrequency.objects.filter(unit=unit).first()
    return frequency if frequency is not None and frequency.schema == unit.schema else None


# A count made while a page waits gives up after this time; the command refresh_units, run on
# the Mac, counts without limit.
FREQUENCY_SECONDS = 10


class FrequencyTooLong(Exception):
    """The occurrences of a schema could not be counted in the time given."""


def refresh_frequency(unit, seconds=None):
    """Count the occurrences of the schema in the analysed corpus; None when it cannot.

    Raise FrequencyTooLong when counting takes longer than ``seconds`` or than the timeout of
    the site: the unit then has no frequency for its present schema.
    """
    if not unit.schema:
        UnitFrequency.objects.filter(unit=unit).delete()
        return None
    layer = default_layer()
    if layer is None:
        return None
    with TimeLimit(seconds) as limit:
        rows = list(count_by_author(schema_matches(unit.edges, layer)))
    if limit.exceeded:
        raise FrequencyTooLong
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
    refresh_unit_forms(unit)
    return unit


@transaction.atomic
def update_unit(unit, user):
    """Save a changed unit; a new schema has its frequency and its forms computed again."""
    _check_edit(user, unit)
    previous = Unit.objects.values("schema", "reference_form").get(pk=unit.pk)
    revision = save_with_revision(unit, user)
    if current_frequency(unit) is None:
        # A count too long to wait for is left for later: the change is saved all the same.
        with suppress(FrequencyTooLong):
            refresh_frequency(unit, FREQUENCY_SECONDS)
    if previous != {"schema": unit.schema, "reference_form": unit.reference_form}:
        refresh_unit_forms(unit)
    _check_still_complete(unit)
    return revision


@transaction.atomic
def convert_schema(unit, administrator):
    """Write the prepositional phrases of a schema with the preposition first; None if none is
    written as the analysis writes it.

    Run by an administrator on every unit, drafts included (``convert_schemas``): the schema
    keeps its lemmas and its meaning, so its forms stay, but the change is recorded like any
    other and its frequency is counted again.
    """
    written = format_schema(unit.edges)
    if written == unit.schema or not writes_case(unit.schema):
        return None
    unit.schema = written
    revision = save_with_revision(
        unit, administrator, gettext("Schéma converti : préposition en tête du syntagme.")
    )
    with suppress(FrequencyTooLong):
        refresh_frequency(unit)
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
    unit,
    attestations,
    user,
    sense=None,
    realization=None,
    origin=Attestation.Origin.MANUAL,
    note="",
    example_proposed=False,
):
    """Attach corpus words to a unit; words already attested for it are skipped.

    ``note`` and ``example_proposed`` come with an attestation chosen in the text being read.
    """
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
            note=note,
            example_proposed=example_proposed,
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


REVIEW_STATUSES = (Attestation.Status.VALIDATED, Attestation.Status.REJECTED)


def _review(attestation, reviewer, status, sense=None, realization=None):
    """Record a reviewer's decision; a validated one may also receive a sense or a realization."""
    if not is_reviewer(reviewer) or not can_view(reviewer, attestation):
        raise PermissionDenied
    validating = status == Attestation.Status.VALIDATED
    if (
        validating
        and attestation.level == Attestation.Level.AUTOMATIC
        and not attestation.passage.edition.work.is_core
    ):
        raise ValidationError(
            gettext(
                "Hors du noyau, une attestation repérée automatiquement n’est pas validée ; "
                "un relecteur peut la rejeter."
            ),
            code="outside_core",
        )
    placing = validating and (sense is not None or realization is not None)
    if attestation.is_withdrawn or (attestation.status == status and not placing):
        return None
    attestation.status = status
    if validating:
        attestation.level = Attestation.Level.VALIDATED
        attestation.sense = sense or attestation.sense
        attestation.realization = realization or attestation.realization
        comment = gettext("Attestation validée")
    else:
        attestation.is_example = False
        comment = gettext("Attestation rejetée")
    attestation.reviewed_by = reviewer
    attestation.reviewed_at = timezone.now()
    return save_with_revision(attestation, reviewer, comment=comment)


@transaction.atomic
def review_attestation(attestation, reviewer, status):
    """A reviewer validates or rejects an attestation; once checked, it is no longer automatic."""
    if status not in REVIEW_STATUSES:
        raise ValueError("An attestation is validated or rejected.")
    attestation = (
        Attestation.objects.select_for_update(of=("self",))
        .select_related("unit", "passage__edition__work")
        .get(pk=attestation.pk)
    )
    revision = _review(attestation, reviewer, status)
    if revision is not None:
        _check_still_complete(attestation.unit)
    return revision


@transaction.atomic
def review_attestations(unit, ids, reviewer, status, sense=None, realization=None):
    """A reviewer validates attestations of the core, or rejects attestations, in one batch.

    Validation is for the core, whose attestations are checked by people; outside it,
    attestations found automatically stay so (T2). The validated attestations may be given a
    sense or a realization of the unit.
    """
    if status not in REVIEW_STATUSES:
        raise ValueError("An attestation is validated or rejected.")
    if not is_reviewer(reviewer) or not can_view(reviewer, unit):
        raise PermissionDenied
    for part in (sense, realization):
        if part is not None and part.unit_id != unit.pk:
            raise ValueError("The sense or the realization belongs to another unit.")
    attestations = unit.attestations.active().filter(pk__in=ids)
    if status == Attestation.Status.VALIDATED:
        attestations = attestations.filter(passage__edition__work__is_core=True)
    attestations = (
        attestations.select_for_update(of=("self",))
        .select_related("unit", "passage__edition__work")
        .order_by("pk")
    )
    revisions = []
    for attestation in attestations:
        revision = _review(attestation, reviewer, status, sense, realization)
        if revision is not None:
            revisions.append(revision)
    _check_still_complete(unit)
    return revisions


# Survey of the occurrences

SURVEY_LIMIT = 1000


@transaction.atomic
def record_automatic_attestations(unit, occurrences, user):
    """Record occurrences of the corpus, word identifiers in textual order, as found automatically.

    In the core they are to be reviewed; outside it they stay found automatically (T2).
    """
    _check_edit(user, unit)
    passages = dict(
        Token.objects.filter(pk__in=[words[0] for words in occurrences]).values_list(
            "pk", "passage_id"
        )
    )
    created = []
    for words in occurrences:
        attestation = Attestation(
            unit=unit,
            passage_id=passages[words[0]],
            level=Attestation.Level.AUTOMATIC,
            origin=Attestation.Origin.QUERY,
            created_by=user,
        )
        save_with_revision(
            attestation, user, comment=gettext("Relevé automatique"), m2m={"tokens": list(words)}
        )
        created.append(attestation)
    return created


@transaction.atomic
def survey_unit(unit, user):
    """Record the occurrences of the schema in the corpus as automatic attestations.

    Those of the core, recorded first, are to be reviewed; the others stay found
    automatically (T2). An occurrence whose words an attestation of the unit already covers,
    even a rejected one, is left aside. A survey adds at most SURVEY_LIMIT attestations; the
    next one goes on.
    """
    _check_edit(user, unit)
    if not unit.schema:
        raise ValidationError(
            gettext("Le relevé part du schéma de l’unité, qui reste à indiquer."), code="no_schema"
        )
    layer = default_layer()
    if layer is None:
        raise ValidationError(gettext("Le relevé demande un corpus analysé."), code="no_layer")
    edges = unit.edges
    rows = list(
        schema_matches(edges, layer)
        .order_by(
            "-token__edition__work__is_core",
            "token__edition__work__author__birth_year",
            "token__edition__work__cts_urn",
            "token__position",
            "part",
        )
        .values_list("token_id", "part", "token__position", "token__edition__work__is_core")
    )
    words = occurrence_words([row[:3] for row in rows], edges, layer)
    # Word sets in the order found, each with whether it is in the core.
    occurrences = dict(zip(words, (row[3] for row in rows), strict=True))
    covered = defaultdict(set)
    rows = Attestation.tokens.through.objects.filter(
        attestation__unit=unit, attestation__is_withdrawn=False
    ).values_list("attestation_id", "token_id")
    for attestation_id, token_id in rows:
        covered[attestation_id].add(token_id)
    by_word = defaultdict(list)
    for words in covered.values():
        for token_id in words:
            by_word[token_id].append(words)
    new = [
        words
        for words in occurrences
        if not any(set(words) <= attested for attested in by_word[words[0]])
    ]
    added = new[:SURVEY_LIMIT]
    record_automatic_attestations(unit, added, user)
    survey, _created = UnitSurvey.objects.update_or_create(
        unit=unit,
        defaults={
            "schema": unit.schema,
            "corpus_version": corpus_version().label,
            "found": len(occurrences),
            "core_found": sum(occurrences.values()),
            "added": len(added),
            "remaining": len(new) - len(added),
            "surveyed_by": user,
            "surveyed_at": timezone.now(),
        },
    )
    return survey


@transaction.atomic
def set_example(attestation, user, is_example):
    """Choose an attestation as an example shown at the top of the unit, or stop showing it."""
    _check_edit(user, attestation.unit)
    if is_example and attestation.status == Attestation.Status.REJECTED:
        raise ValidationError(
            gettext("Une attestation rejetée ne sert pas d’exemple."), code="rejected_example"
        )
    attestation.is_example = is_example
    if is_example:
        attestation.example_proposed = False
    revision = save_with_revision(attestation, user)
    _check_still_complete(attestation.unit)
    return revision


# Doubts and contests about an attestation


@transaction.atomic
def doubt_attestation(attestation, user, reason):
    """Signal an attestation thought wrong, with the reason; a reviewer decides."""
    if not (user.is_authenticated and user.is_active and can_view(user, attestation)):
        raise PermissionDenied
    if attestation.is_withdrawn or attestation.status == Attestation.Status.REJECTED:
        raise ValidationError(gettext("Cette attestation est déjà écartée."), code="not_doubtable")
    open_doubts = attestation.doubts.filter(status=AttestationDoubt.Status.OPEN)
    if open_doubts.filter(created_by=user).exists():
        raise ValidationError(
            gettext("Vous avez déjà signalé cette attestation comme douteuse."),
            code="already_doubted",
        )
    doubt = AttestationDoubt(attestation=attestation, reason=reason, created_by=user)
    save_with_revision(doubt, user)
    return doubt


@transaction.atomic
def decide_doubts(attestation, reviewer, reject):
    """A reviewer settles the open doubts about an attestation: kept, or rejected with them."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    doubts = list(
        attestation.doubts.select_for_update().filter(status=AttestationDoubt.Status.OPEN)
    )
    if not doubts:
        raise ValidationError(gettext("Aucun doute ouvert sur cette attestation."), code="no_doubt")
    if reject:
        review_attestation(attestation, reviewer, Attestation.Status.REJECTED)
    status = AttestationDoubt.Status.REJECTED if reject else AttestationDoubt.Status.KEPT
    now = timezone.now()
    for doubt in doubts:
        doubt.status, doubt.decided_by, doubt.decided_at = status, reviewer, now
        save_with_revision(doubt, reviewer, comment=gettext("Doute tranché"))
    return doubts


@transaction.atomic
def contest_attestation(attestation, user, argument):
    """Contest an attestation: the argument opens its discussion, with indicative votes (Q48)."""
    attestation = (
        Attestation.objects.select_for_update(of=("self",))
        .select_related("unit")
        .get(pk=attestation.pk)
    )
    if not (user.is_authenticated and user.is_active and can_view(user, attestation)):
        raise PermissionDenied
    if (
        attestation.is_withdrawn
        or attestation.is_hidden
        or attestation.is_contested
        or attestation.status == Attestation.Status.REJECTED
    ):
        raise ValidationError(
            gettext("Cette attestation ne peut pas être contestée."), code="not_contestable"
        )
    attestation.is_contested = True
    save_with_revision(attestation, user, comment=gettext("Contestation"))
    post_comment(attestation, user, argument)
    return attestation


CONTEST_DECISIONS = ("keep", "validate", "reject")


@transaction.atomic
def resolve_attestation_contest(attestation, reviewer, decision, reason):
    """A reviewer settles a contest, giving the reason: the attestation kept, validated or rejected.

    The arguments stay in the discussion (Q53).
    """
    if decision not in CONTEST_DECISIONS:
        raise ValueError("A contest is settled by keep, validate or reject.")
    if not is_reviewer(reviewer):
        raise PermissionDenied
    attestation = (
        Attestation.objects.select_for_update(of=("self",))
        .select_related("unit", "passage__edition__work")
        .get(pk=attestation.pk)
    )
    if not attestation.is_contested:
        raise ValidationError(
            gettext("Cette attestation n’est pas contestée."), code="not_contested"
        )
    post_comment(attestation, reviewer, reason)
    if decision != "keep":
        status = (
            Attestation.Status.VALIDATED if decision == "validate" else Attestation.Status.REJECTED
        )
        _review(attestation, reviewer, status)
    attestation.is_contested = False
    revision = save_with_revision(attestation, reviewer, comment=gettext("Contestation levée"))
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


# Abstract words


@transaction.atomic
def create_abstract_word(word, author):
    """An abstract word is public at once, proposed until a reviewer validates it."""
    word.created_by = author
    word.status = AbstractWord.Status.PROPOSED
    save_with_revision(word, author)
    return word


@transaction.atomic
def update_abstract_word(word, user):
    if not can_edit_abstract_word(user, word):
        raise PermissionDenied
    return save_with_revision(word, user)


@transaction.atomic
def validate_abstract_word(word, reviewer):
    if not is_reviewer(reviewer):
        raise PermissionDenied
    word = AbstractWord.objects.select_for_update().get(pk=word.pk)
    if word.status == AbstractWord.Status.VALIDATED:
        return None
    word.status = AbstractWord.Status.VALIDATED
    word.validated_by = reviewer
    word.validated_at = timezone.now()
    return save_with_revision(word, reviewer, comment=gettext("Validation"))


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
    with suppress(FrequencyTooLong):
        refresh_frequency(unit, FREQUENCY_SECONDS)
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


# Searches that find nothing


def recorded_search_form(search):
    """The search form of a recorded search, validated; None if the search is no longer valid."""
    form = bound_search_form(QueryDict(search.query))
    return form if form.is_valid() else None


@transaction.atomic
def record_negative_search(search, author):
    """Record a search that finds nothing, with the version of the corpus searched (rule 7)."""
    search.query = search_query(QueryDict(search.query))
    form = recorded_search_form(search)
    if form is None:
        raise ValidationError(
            gettext("Cette recherche n’est pas valide : refaites-la."), code="invalid_search"
        )
    if form.hits().exists():
        raise ValidationError(
            gettext("Cette recherche trouve des occurrences : elle n’est pas infructueuse."),
            code="found",
        )
    search.corpus_version = corpus_version().label
    search.created_by = author
    save_with_revision(search, author)
    return search
