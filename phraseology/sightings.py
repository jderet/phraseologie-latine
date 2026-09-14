"""Sightings: words where a reader sees phraseology without choosing an entry yet.

They wait in a queue: any active account attaches one to an entry, existing or new, and the
attestation obtained is proposed; a reviewer may dismiss a sighting.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.roles import is_reviewer
from justifications.services import corpus_evidence
from moderation.services import save_with_revision

from .models import Sighting


@transaction.atomic
def create_sighting(words, user, note=""):
    """Record words where there is phraseology, from their identifiers, with a note."""
    if not (user.is_authenticated and user.is_active):
        raise PermissionDenied
    evidence = corpus_evidence(words)
    sighting = Sighting(passage=evidence.tokens[0].passage, note=note, created_by=user)
    save_with_revision(sighting, user, m2m={"tokens": evidence.tokens})
    return sighting


def open_sighting(value):
    """The open sighting a form refers to by its identifier, if any."""
    value = str(value or "")
    if not value.isdigit():
        return None
    return Sighting.objects.filter(
        pk=int(value), status=Sighting.Status.OPEN, is_hidden=False
    ).first()


def sighting_words(sighting):
    """The identifiers of the words of a sighting, in textual order, as forms send them."""
    ids = sighting.tokens.order_by("position").values_list("pk", flat=True)
    return ",".join(str(pk) for pk in ids)


def attestation_for(unit, words):
    """The attestation of a unit covering exactly these words, if there is one."""
    wanted = {int(pk) for pk in str(words).split(",") if pk.strip().isdigit()}
    for attestation in unit.attestations.active().prefetch_related("tokens"):
        if {token.pk for token in attestation.tokens.all()} == wanted:
            return attestation
    return None


@transaction.atomic
def close_sighting(sighting, attestation, user):
    """Record that the words of a sighting now attest a unit; None if it was already closed."""
    sighting = Sighting.objects.select_for_update().get(pk=sighting.pk)
    if sighting.status != Sighting.Status.OPEN or attestation is None:
        return None
    sighting.status = Sighting.Status.ATTACHED
    sighting.attestation = attestation
    sighting.decided_by = user
    sighting.decided_at = timezone.now()
    return save_with_revision(sighting, user, comment=gettext("Repérage rattaché à une fiche"))


@transaction.atomic
def dismiss_sighting(sighting, reviewer):
    """A reviewer dismisses a sighting that attests no unit."""
    if not is_reviewer(reviewer):
        raise PermissionDenied
    sighting = Sighting.objects.select_for_update().get(pk=sighting.pk)
    if sighting.status != Sighting.Status.OPEN:
        raise ValidationError(gettext("Ce repérage est déjà traité."), code="closed")
    sighting.status = Sighting.Status.DISMISSED
    sighting.decided_by = reviewer
    sighting.decided_at = timezone.now()
    return save_with_revision(sighting, reviewer, comment=gettext("Repérage classé sans suite"))


@dataclass
class SightingMark:
    """An open sighting drawn among the words of a page, for annotators."""

    sighting: Sighting
    words: list
    start: int
    end: int
    track: int = 0
    edition: int = 0

    @property
    def key(self):
        """The sighting and its words, which the reading script reads back."""
        return "_".join(["r", str(self.sighting.pk), *(str(pk) for pk in self.words)])

    @property
    def css(self):
        return f"u k-none s-sighting t{self.track}"


def page_sightings(passages, token_ids):
    """The open sightings beginning in the passages of a page, with their words there."""
    sightings = {
        sighting.pk: sighting
        for sighting in Sighting.objects.filter(
            passage__in=passages, status=Sighting.Status.OPEN, is_hidden=False
        )
    }
    rows = (
        Sighting.tokens.through.objects.filter(sighting_id__in=list(sightings))
        .order_by("token__position")
        .values_list("sighting_id", "token_id", "token__position", "token__edition_id")
    )
    found, editions = defaultdict(list), {}
    for sighting_id, token_id, position, edition_id in rows:
        if token_id in token_ids:
            found[sighting_id].append((position, token_id))
            editions[sighting_id] = edition_id
    return [
        SightingMark(
            sightings[pk],
            [token_id for _position, token_id in words],
            words[0][0],
            words[-1][0],
            edition=editions[pk],
        )
        for pk, words in found.items()
    ]
