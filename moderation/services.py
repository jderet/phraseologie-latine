"""Recording, reverting and hiding contributed content; handling reports.

Views decide who may edit a given content; these functions record every change and
enforce the rules shared by all contents (limits of new accounts, visibility, roles).
"""

import json

from django.contrib.contenttypes.models import ContentType
from django.core import serializers
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext

from accounts.limits import check_can_contribute, check_text_for_links, is_limited
from accounts.roles import is_reviewer

from .models import Comment, Report, Revision, Vote
from .registry import can_revert, can_view, get_registration, is_owner

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
def save_with_revision(obj, author, comment="", m2m=None):
    """Save a moderated object and record the change; return None if nothing changed.

    ``m2m`` maps many-to-many fields to the values set before the new state is recorded.
    """
    registration = get_registration(obj)
    creating = obj._state.adding
    check_can_contribute(author, counted=creating and registration.counts_toward_limit)
    before = None if creating else snapshot(_locked(obj))
    # Only the text this change writes is checked: closing a proposal whose explanation holds a
    # link, for instance, does not block a new account.
    written = [
        getattr(obj, name)
        for name in registration.text_fields
        if creating or before.get(name) != getattr(obj, name)
    ]
    check_text_for_links(author, *written)
    obj.save()
    for name, values in (m2m or {}).items():
        getattr(obj, name).set(values)
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
    check_can_contribute(user, counted=False)
    skipped = NOT_REVERTED | set(get_registration(obj).not_reverted)
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
            and field.name not in skipped
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


def can_comment(user, obj):
    discussion = get_registration(obj).discussion
    return bool(
        discussion
        and user.is_authenticated
        and user.is_active
        and can_view(user, obj)
        and discussion(user, obj)
    )


@transaction.atomic
def post_comment(obj, user, text):
    """Post a message in the discussion of a content; a message is itself a content."""
    if not can_comment(user, obj):
        raise PermissionDenied
    comment = Comment(content_object=obj, author=user, text=text)
    save_with_revision(comment, user)
    return comment


def comments_for(user, obj):
    """Messages of a discussion that the user may see."""
    comments = []
    for comment in Comment.objects.for_object(obj).select_related("author"):
        comment.content_object = obj
        if can_view(user, comment):
            comments.append(comment)
    return comments


def can_vote(user, obj):
    """Confirmed accounts vote on what they see, except on what they own."""
    votes = get_registration(obj).votes
    return bool(
        votes
        and user.is_authenticated
        and user.is_active
        and not is_limited(user)
        and can_view(user, obj)
        and not is_owner(user, obj)
        and votes(user, obj)
    )


@transaction.atomic
def cast_vote(obj, user, value):
    """Record or change the user's vote on a content; the value 0 removes it."""
    if not can_vote(user, obj):
        raise PermissionDenied
    content_type = ContentType.objects.get_for_model(obj)
    if value == 0:
        Vote.objects.filter(author=user, content_type=content_type, object_id=obj.pk).delete()
        return None
    if value not in Vote.Value.values:
        raise ValueError("A vote is 1 or -1.")
    vote, _created = Vote.objects.update_or_create(
        author=user, content_type=content_type, object_id=obj.pk, defaults={"value": value}
    )
    return vote


def vote_summary(user, obj):
    content_type = ContentType.objects.get_for_model(obj)
    votes = Vote.objects.filter(content_type=content_type, object_id=obj.pk)
    counts = dict(votes.values_list("value").annotate(count=Count("pk")).order_by())
    current = None
    if user.is_authenticated:
        current = votes.filter(author=user).values_list("value", flat=True).first()
    return {
        "for": counts.get(Vote.Value.FOR, 0),
        "against": counts.get(Vote.Value.AGAINST, 0),
        "current": current,
    }
