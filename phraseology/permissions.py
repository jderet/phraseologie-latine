"""Who may change which phraseology content; views check these rules on the server."""

from accounts.roles import is_reviewer
from moderation.registry import can_view


def can_edit_unit(user, unit):
    """Its creator writes a draft; once proposed, any active account completes a unit.

    Every change stays in the history and can be reverted (choice of 14 September 2026).
    """
    if not (user.is_authenticated and user.is_active and can_view(user, unit)):
        return False
    if unit.is_hidden:
        return is_reviewer(user)
    return not unit.is_draft or user.pk == unit.created_by_id


def can_edit_neologism(user, neologism):
    """Neologisms are public from the start: any active account completes them, like units."""
    if not (user.is_authenticated and user.is_active and can_view(user, neologism)):
        return False
    return not neologism.is_hidden or is_reviewer(user)


def can_withdraw_attestation(user, attestation):
    """Its author withdraws an attestation not yet validated; a reviewer, any attestation."""
    if not can_edit_unit(user, attestation.unit) or attestation.is_withdrawn:
        return False
    if is_reviewer(user):
        return True
    return (
        user.pk == attestation.created_by_id and attestation.status != attestation.Status.VALIDATED
    )
