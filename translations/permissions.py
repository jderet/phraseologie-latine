"""Who may change which translation content; views check these rules on the server."""

from accounts.roles import is_reviewer
from moderation.registry import can_view, is_owner

from .models import is_version_writer


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
    """Its author and co-authors write the Latin of a version, until the variant is closed."""
    return (
        user.is_active
        and not version.is_closed
        and is_version_writer(user, version)
        and can_view(user, version)
    )


def can_manage(user, version):
    """Only its author publishes a version, changes its settings and chooses its co-authors."""
    return user.is_active and is_owner(user, version) and can_view(user, version)


def can_copy(user, step):
    """Any active account may start a variant from a public step of the main version, like a
    Git fork; a variant is never copied."""
    version = step.version
    return (
        user.is_authenticated
        and user.is_active
        and version.is_main
        and version.is_published
        and not version.is_hidden
        and not version.project.is_hidden
        and not step.is_hidden
        and (not step.during_draft or version.shows_draft_steps)
    )


def can_propose(user, version):
    """Anyone but its writers may propose changes to a published version that is not closed;
    they decide."""
    return not version.is_closed and can_challenge(user, version)


def can_challenge(user, version):
    """Anyone but its writers may contest the choices of a published version."""
    return (
        user.is_authenticated
        and user.is_active
        and version.is_published
        and not version.is_hidden
        and not is_version_writer(user, version)
    )
