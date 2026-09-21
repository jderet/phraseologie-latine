"""Who may change which translation content; views check these rules on the server."""

from accounts.roles import is_reviewer
from moderation.registry import can_view, is_owner

from .models import TranslationProject, is_editor, is_version_writer


def can_edit(user, obj):
    """The owner of a content, or a reviewer, may change its information; a project is also
    changed by its editors (choice of 21 September 2026)."""
    if not can_view(user, obj):
        return False
    if isinstance(obj, TranslationProject):
        return is_editor(user, obj) or is_reviewer(user)
    return is_owner(user, obj) or is_reviewer(user)


def can_change_source(user, source):
    """Whoever added a source text, and reviewers, add, edit, merge or split its sentences."""
    return user.is_authenticated and user.is_active and can_edit(user, source)


def can_propose_source(user, source):
    """Any other active account may propose changes to the sentences of a text."""
    return (
        user.is_authenticated
        and user.is_active
        and not source.is_hidden
        and can_view(user, source)
        and not can_change_source(user, source)
    )


def can_translate(user, version):
    """Its author and co-authors write the Latin of a translation."""
    return user.is_active and is_version_writer(user, version) and can_view(user, version)


def can_manage(user, version):
    """The editors of the project publish its translation and choose its settings."""
    return user.is_active and is_editor(user, version.project) and can_view(user, version)


def can_challenge(user, version):
    """Anyone but its writers may contest the choices of a published version."""
    return (
        user.is_authenticated
        and user.is_active
        and version.is_published
        and not version.is_hidden
        and not is_version_writer(user, version)
    )
