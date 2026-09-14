"""Corrections of the automatic analysis, proposed by readers and validated by reviewers (Q28).

A correction points to a word, never to a layer (rule 1). Once validated it is written into the
default layer, which the reading, the search and the surveys query; making another layer the
default applies every validated correction to it again, so corrections survive a new analysis.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.roles import is_reviewer
from moderation.services import save_with_revision

from .models import AnalysisCorrection, TokenAnalysis
from .search import default_layer
from .text import normalize

# The fields of an analysis a correction may change.
FIELDS = ("lemma", "upos", "feats", "deprel", "head")


def current_analysis(token, part=0, layer=None):
    """The analysis of a part of a word in a layer, or None."""
    layer = layer or default_layer()
    if layer is None:
        return None
    return TokenAnalysis.objects.filter(layer=layer, token=token, part=part).first()


def correction_changes(correction):
    """What a correction sets, as (label, value): the fields it fills."""
    changes = []
    for field in FIELDS:
        value = getattr(correction, field)
        if value:
            label = AnalysisCorrection._meta.get_field(field).verbose_name
            changes.append((label, value.form if field == "head" else value))
    return changes


def _changes(correction, analysis):
    """The fields the correction sets to a new value."""
    changed = []
    for field in FIELDS:
        if field == "head":
            if correction.head_id is not None and (
                analysis is None or analysis.head_id != correction.head_id
            ):
                changed.append(field)
        elif getattr(correction, field) and (
            analysis is None or getattr(analysis, field) != getattr(correction, field)
        ):
            changed.append(field)
    return changed


@transaction.atomic
def propose_correction(correction, user):
    """A reader proposes a correction of the analysis of a word, with the reason."""
    if not (user.is_authenticated and user.is_active):
        raise PermissionDenied
    token = correction.token
    if correction.head_id is not None and correction.head.edition_id != token.edition_id:
        raise ValidationError(
            gettext("Le mot dont il dépend doit être du même texte."), code="head_elsewhere"
        )
    if not _changes(correction, current_analysis(token, correction.part)):
        raise ValidationError(
            gettext("La correction ne change rien à l’analyse actuelle."), code="no_change"
        )
    correction.created_by = user
    correction.status = AnalysisCorrection.Status.PROPOSED
    save_with_revision(correction, user)
    return correction


def apply_correction(correction, layer):
    """Write a validated correction into a layer, over the automatic analysis."""
    analysis, _created = TokenAnalysis.objects.get_or_create(
        layer=layer,
        token=correction.token,
        part=correction.part,
        defaults={"text": correction.token.form},
    )
    for field in FIELDS:
        if field == "head":
            if correction.head_id is not None:
                analysis.head_id = correction.head_id
        elif getattr(correction, field):
            setattr(analysis, field, getattr(correction, field))
    analysis.lemma_norm = normalize(analysis.lemma) if analysis.lemma else ""
    analysis.origin = TokenAnalysis.Origin.CORRECTED
    analysis.save()
    return analysis


def apply_corrections(layer):
    """Apply every validated correction to a layer, in the order they were validated."""
    corrections = AnalysisCorrection.objects.filter(
        status=AnalysisCorrection.Status.VALIDATED, is_hidden=False
    ).select_related("token")
    count = 0
    for correction in corrections.order_by("reviewed_at", "pk"):
        apply_correction(correction, layer)
        count += 1
    return count


@transaction.atomic
def review_correction(correction, reviewer, status):
    """A reviewer validates a correction, which then applies to the default layer, or rejects it."""
    if status not in (AnalysisCorrection.Status.VALIDATED, AnalysisCorrection.Status.REJECTED):
        raise ValueError("A correction is validated or rejected.")
    if not is_reviewer(reviewer):
        raise PermissionDenied
    correction = AnalysisCorrection.objects.select_for_update().get(pk=correction.pk)
    if correction.status != AnalysisCorrection.Status.PROPOSED:
        raise ValidationError(gettext("Cette correction est déjà examinée."), code="reviewed")
    correction.status = status
    correction.reviewed_by = reviewer
    correction.reviewed_at = timezone.now()
    revision = save_with_revision(correction, reviewer)
    layer = default_layer()
    if status == AnalysisCorrection.Status.VALIDATED and layer is not None:
        apply_correction(correction, layer)
    return revision
