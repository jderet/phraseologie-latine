"""Who may change which translation content; views check these rules on the server."""

from accounts.roles import is_reviewer
from moderation.registry import can_view, is_owner


def can_edit(user, obj):
    """The owner of a content, or a reviewer, may change its information."""
    return can_view(user, obj) and (is_owner(user, obj) or is_reviewer(user))


def can_translate(user, version):
    """Only its author writes the Latin of a version."""
    return user.is_active and is_owner(user, version) and can_view(user, version)
