"""Who may change which translation content; views check these rules on the server."""

from accounts.roles import is_reviewer
from moderation.registry import can_view, is_owner


def can_edit(user, obj):
    """The owner of a content, or a reviewer, may change its information."""
    return can_view(user, obj) and (is_owner(user, obj) or is_reviewer(user))


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
    """Only its author writes the Latin of a version."""
    return user.is_active and is_owner(user, version) and can_view(user, version)


def can_copy(user, step):
    """Any active account may start its own version from a public step, like a Git fork."""
    version = step.version
    return (
        user.is_authenticated
        and user.is_active
        and version.is_published
        and not version.is_hidden
        and not version.project.is_hidden
        and not step.is_hidden
        and (not step.during_draft or version.shows_draft_steps)
    )


def can_propose(user, version):
    """Anyone but its author may propose changes to a published version; its author decides."""
    return can_challenge(user, version)


def can_challenge(user, version):
    """Anyone but its author may contest the choices of a published version."""
    return (
        user.is_authenticated
        and user.is_active
        and version.is_published
        and not version.is_hidden
        and user.pk != version.author_id
    )
