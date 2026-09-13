"""Models whose content is moderated: revision history, rollback and reports.

Only registered models get history and report pages, so that no other model (users,
corpus data) can be reached through the generic moderation URLs.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.urls import reverse

from accounts.roles import is_reviewer


class NotRegistered(ImproperlyConfigured):
    pass


@dataclass(frozen=True)
class Registration:
    model: type
    # Foreign key to the user who owns the content (may revert it, sees it when hidden);
    # dots follow relations, as in "version.author"; a function returns the owner's id.
    owner_field: str | Callable | None = None
    # Free-text fields checked for links when the author is a new account.
    text_fields: tuple[str, ...] = ()
    # Extra visibility rule, e.g. drafts visible to their author only.
    visible_to: Callable | None = None
    # Whether creating such a content counts toward the daily limit of new accounts; parts
    # of a counted content, like the sentences of a translation, do not.
    counts_toward_limit: bool = True
    # Fields a revert never restores, e.g. the publication of a version.
    not_reverted: tuple[str, ...] = ()
    # Who may post in the discussion of a content (function of user and content); None: no
    # discussion. Viewing the content is also required.
    discussion: Callable | None = None
    # Who may vote on a content, besides being able to view it, not owning it and not being a
    # new account; None: no votes.
    votes: Callable | None = None


_registry: dict[type, Registration] = {}


def register(
    model,
    *,
    owner_field=None,
    text_fields=(),
    visible_to=None,
    counts_toward_limit=True,
    not_reverted=(),
    discussion=None,
    votes=None,
):
    try:
        model._meta.get_field("is_hidden")
    except FieldDoesNotExist as error:
        raise ImproperlyConfigured(
            f"{model._meta.label} must inherit from moderation.models.ModeratedContent."
        ) from error
    _registry[model] = Registration(
        model,
        owner_field,
        tuple(text_fields),
        visible_to,
        counts_toward_limit,
        tuple(not_reverted),
        discussion,
        votes,
    )
    return model


def get_registration(model_or_instance):
    model = model_or_instance if isinstance(model_or_instance, type) else type(model_or_instance)
    model = model._meta.concrete_model
    try:
        return _registry[model]
    except KeyError as error:
        raise NotRegistered(f"{model._meta.label} is not registered for moderation.") from error


def find_registration(app_label, model_name):
    for model, registration in _registry.items():
        if model._meta.app_label == app_label and model._meta.model_name == model_name:
            return registration
    return None


def uncounted_models():
    """Models whose creation does not count toward the daily limit of new accounts."""
    return [
        model for model, registration in _registry.items() if not registration.counts_toward_limit
    ]


def owner_id(obj):
    owner_field = get_registration(obj).owner_field
    if not owner_field:
        return None
    if callable(owner_field):
        return owner_field(obj)
    *path, name = owner_field.split(".")
    for step in path:
        obj = getattr(obj, step)
    return getattr(obj, f"{name}_id")


def is_owner(user, obj):
    return bool(user.is_authenticated and owner_id(obj) is not None and owner_id(obj) == user.pk)


def can_view(user, obj):
    registration = get_registration(obj)
    if registration.visible_to is not None and not registration.visible_to(user, obj):
        return False
    if obj.is_hidden:
        return is_reviewer(user) or is_owner(user, obj)
    return True


def can_revert(user, obj):
    return can_view(user, obj) and (is_reviewer(user) or is_owner(user, obj))


def _object_args(obj):
    return [obj._meta.app_label, obj._meta.model_name, obj.pk]


def history_url(obj):
    return reverse("moderation:history", args=_object_args(obj))


def report_url(obj):
    return reverse("moderation:report", args=_object_args(obj))


def comment_url(obj):
    return reverse("moderation:comment", args=_object_args(obj))


def vote_url(obj):
    return reverse("moderation:vote", args=_object_args(obj))
