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
    # Foreign key to the user who owns the content (may revert it, sees it when hidden).
    owner_field: str | None = None
    # Free-text fields checked for links when the author is a new account.
    text_fields: tuple[str, ...] = ()
    # Extra visibility rule, e.g. drafts visible to their author only.
    visible_to: Callable | None = None


_registry: dict[type, Registration] = {}


def register(model, *, owner_field=None, text_fields=(), visible_to=None):
    try:
        model._meta.get_field("is_hidden")
    except FieldDoesNotExist as error:
        raise ImproperlyConfigured(
            f"{model._meta.label} must inherit from moderation.models.ModeratedContent."
        ) from error
    _registry[model] = Registration(model, owner_field, tuple(text_fields), visible_to)
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


def is_owner(user, obj):
    owner_field = get_registration(obj).owner_field
    return bool(
        owner_field and user.is_authenticated and getattr(obj, f"{owner_field}_id") == user.pk
    )


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
