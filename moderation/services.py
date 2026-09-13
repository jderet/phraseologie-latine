"""Recording, reverting and hiding contributed content; handling reports.

Views decide who may edit a given content; these functions record every change and
enforce the rules shared by all contents (limits of new accounts, visibility, roles).
"""

import json

from django.core import serializers
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.limits import check_can_contribute, check_text_for_links
from accounts.roles import is_reviewer

from .models import Report, Revision
from .registry import can_revert, can_view, get_registration

# Visibility is changed only by hiding or unhiding, never by a revert.
NOT_REVERTED = {"is_hidden"}


def snapshot(obj):
    """State of an object as stored in a revision, with JSON values."""
    names = [
        field.name
        for field in (*obj._meta.concrete_fields, *obj._meta.many_to_many)
        if not field.primary_key and not getattr(field, "auto_now", False)
    ]
    fields = serializers.serialize("python", [obj], fields=names)[0]["fields"]
    return json.loads(json.dumps(fields, cls=DjangoJSONEncoder))


def _locked(obj):
    return type(obj)._base_manager.select_for_update().get(pk=obj.pk)


def _record(obj, author, action, before, comment="", reverted_to=None):
    return Revision.objects.create(
        content_object=obj,
        author=author,
        action=action,
        before=before,
        after=snapshot(obj),
        comment=comment,
        reverted_to=reverted_to,
    )


@transaction.atomic
def save_with_revision(obj, author, comment=""):
    """Save a moderated object and record the change; return None if nothing changed."""
    registration = get_registration(obj)
    check_can_contribute(author)
    check_text_for_links(author, *(getattr(obj, name) for name in registration.text_fields))
    creating = obj._state.adding
    before = None if creating else snapshot(_locked(obj))
    obj.save()
    if not creating and snapshot(obj) == before:
        return None
    action = Revision.Action.CREATE if creating else Revision.Action.UPDATE
    return _record(obj, author, action, before, comment)


@transaction.atomic
def revert_to(revision, user, comment=""):
    """Restore the state recorded by a revision, as a new revision; None if already so."""
    model = revision.content_type.model_class()
    obj = model._base_manager.select_for_update().get(pk=revision.object_id)
    if not can_revert(user, obj):
        raise PermissionDenied
    if not is_reviewer(user):
        check_can_contribute(user)
    before = snapshot(obj)
    restored = next(
        serializers.deserialize(
            "python",
            [{"model": model._meta.label_lower, "pk": obj.pk, "fields": revision.after}],
            ignorenonexistent=True,
        )
    )
    for field in model._meta.concrete_fields:
        if (
            field.name in revision.after
            and field.name not in NOT_REVERTED
            and not field.primary_key
            and not getattr(field, "auto_now", False)
        ):
            setattr(obj, field.attname, getattr(restored.object, field.attname))
    obj.save()
    for name, values in restored.m2m_data.items():
        getattr(obj, name).set(values)
    if snapshot(obj) == before:
        return None
    return _record(obj, user, Revision.Action.REVERT, before, comment, reverted_to=revision)


def _set_hidden(obj, user, hidden, comment):
    get_registration(obj)
    if not is_reviewer(user):
        raise PermissionDenied
    obj = _locked(obj)
    if obj.is_hidden == hidden:
        return None
    before = snapshot(obj)
    obj.is_hidden = hidden
    obj.save(update_fields=["is_hidden"])
    action = Revision.Action.HIDE if hidden else Revision.Action.UNHIDE
    return _record(obj, user, action, before, comment)


@transaction.atomic
def hide_content(obj, user, comment=""):
    return _set_hidden(obj, user, True, comment)


@transaction.atomic
def unhide_content(obj, user, comment=""):
    return _set_hidden(obj, user, False, comment)


def create_report(user, obj, reason, message=""):
    """Report a content; return (report, created), reusing the user's open report."""
    get_registration(obj)
    if not user.is_authenticated or not can_view(user, obj):
        raise PermissionDenied
    open_reports = Report.objects.filter(
        author=user,
        content_type__app_label=obj._meta.app_label,
        content_type__model=obj._meta.model_name,
        object_id=obj.pk,
        status=Report.Status.OPEN,
    )
    existing = open_reports.first()
    if existing is not None:
        return existing, False
    report = Report.objects.create(content_object=obj, author=user, reason=reason, message=message)
    return report, True


@transaction.atomic
def resolve_report(report, user, status, resolution="", hide=False):
    if not is_reviewer(user):
        raise PermissionDenied
    if report.status != Report.Status.OPEN:
        raise ValueError("Only open reports can be resolved.")
    if hide:
        comment = gettext("Masqué à la suite du signalement n° %(number)s") % {"number": report.pk}
        hide_content(report.content_object, user, comment)
    report.status = status
    report.handled_by = user
    report.handled_at = timezone.now()
    report.resolution = resolution
    report.save()
    return report
