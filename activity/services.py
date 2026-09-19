"""Recording events, telling the people concerned, following contents and starring versions.

Nobody is told about a content they may not see: a draft, the working text or a proposal never
sent stays with those who may read it (rule 8).
"""

import re

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Lower, Replace
from django.utils import timezone

from accounts.models import User
from moderation.registry import can_view

from .models import Event, Notification, Star, Subscription, Verb

# Contents one may follow, by model label.
FOLLOWABLE = {
    "translations.translationproject",
    "translations.translationversion",
    "translations.sourcetext",
    "translations.changeproposal",
    "translations.sourceproposal",
    "translations.topic",
    "justifications.challenge",
}

MENTION = re.compile(r"(?<![\w@])@([\w][\w.-]{1,79})")
MAX_MENTIONS = 10


def _label(obj):
    return obj._meta.label_lower


def parents(obj):
    """The contents an object belongs to, nearest first: a proposal belongs to its version,
    which belongs to its project. Followers of a parent hear about its parts."""
    chain = []
    current = obj
    for _step in range(6):
        current = _parent(current)
        if current is None:
            break
        chain.append(current)
    return chain


def _parent(obj):
    label = _label(obj)
    if label == "moderation.comment":
        return obj.content_object
    if label in ("translations.translationversion",):
        return obj.project
    if label in (
        "translations.changeproposal",
        "translations.versionstep",
        "translations.versionmember",
        "translations.translatedsegment",
    ):
        return obj.version
    if label == "translations.proposedsentence":
        return obj.proposal
    if label == "translations.sourceproposal":
        return obj.source_text
    if label == "justifications.challenge":
        return obj.translated_segment.version
    if label == "justifications.justification":
        return obj.translated_segment.version
    project = getattr(obj, "project", None)
    if project is not None and label != "translations.translationproject":
        return project
    version = getattr(obj, "version", None)
    return version


def project_of(obj):
    for item in (obj, *parents(obj)):
        if _label(item) == "translations.translationproject":
            return item
    return None


def followers(obj):
    """Ids of the people who follow the object or one of its parents, and did not unfollow
    the object itself."""
    targets = [obj, *parents(obj)]
    query = Q()
    for target in targets:
        query |= Q(content_type=ContentType.objects.get_for_model(target), object_id=target.pk)
    rows = Subscription.objects.filter(query).values_list(
        "user_id", "active", "content_type_id", "object_id"
    )
    own_type = ContentType.objects.get_for_model(obj)
    unfollowed = {
        user_id
        for user_id, active, type_id, object_id in rows
        if not active and type_id == own_type.pk and object_id == obj.pk
    }
    return {user_id for user_id, active, *_rest in rows if active} - unfollowed


def mentioned_users(text):
    """Active accounts named in a text by @ and their displayed name, without spaces
    (« @MarcusTullius »). A name several accounts share mentions nobody."""
    names = {match.lower() for match in MENTION.findall(text or "")}
    names = {name.rstrip(".-") for name in names}
    if not names:
        return []
    names = sorted(names)[:MAX_MENTIONS]
    compact = Lower(Replace("display_name", Value(" "), Value("")))
    candidates = (
        User.objects.filter(is_active=True, anonymized_at__isnull=True)
        .annotate(compact=compact)
        .filter(compact__in=names)
    )
    by_name = {}
    for user in candidates:
        by_name.setdefault(user.compact, []).append(user)
    return [users[0] for users in by_name.values() if len(users) == 1]


def mention_handle(user):
    """How to mention someone: @ and their displayed name without spaces."""
    return "@" + "".join(user.public_name.split())


@transaction.atomic
def record(actor, verb, target, recipients=(), mention_text="", notify_followers=True):
    """Record an event and tell the people concerned: ``recipients``, the followers of the
    target and its parents, and the people mentioned in ``mention_text``. Nobody is told about
    their own action or about a content they may not see."""
    event = Event.objects.create(
        actor=actor,
        verb=verb,
        target=target,
        project=project_of(target),
        is_public=can_view(AnonymousUser(), target),
    )
    ids = {user.pk if hasattr(user, "pk") else user for user in recipients}
    if notify_followers:
        ids |= followers(target)
    _notify(event, ids - {actor.pk})
    mentioned = [user for user in mentioned_users(mention_text) if user.pk != actor.pk]
    if mentioned:
        mention = Event.objects.create(
            actor=actor, verb=Verb.MENTIONED, target=target, project=event.project
        )
        _notify(mention, {user.pk for user in mentioned})
    return event


def _notify(event, user_ids):
    if not user_ids:
        return
    target = event.target
    users = User.objects.filter(pk__in=user_ids, is_active=True)
    Notification.objects.bulk_create(
        [Notification(recipient=user, event=event) for user in users if can_view(user, target)],
        ignore_conflicts=True,
    )


def unread_count(user):
    if not user.is_authenticated:
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def mark_read(user, notifications=None):
    queryset = Notification.objects.filter(recipient=user, read_at__isnull=True)
    if notifications is not None:
        queryset = queryset.filter(pk__in=[item.pk for item in notifications])
    return queryset.update(read_at=timezone.now())


# Following


def _subscription_filter(user, obj):
    return {
        "user": user,
        "content_type": ContentType.objects.get_for_model(obj),
        "object_id": obj.pk,
    }


def is_following(user, obj):
    if not user.is_authenticated:
        return False
    return Subscription.objects.filter(**_subscription_filter(user, obj), active=True).exists()


def follow(user, obj):
    """Follow a content one may see."""
    if not user.is_authenticated or not can_view(user, obj):
        return None
    subscription, _created = Subscription.objects.update_or_create(
        **_subscription_filter(user, obj), defaults={"active": True}
    )
    return subscription


def unfollow(user, obj):
    if not user.is_authenticated:
        return
    Subscription.objects.update_or_create(
        **_subscription_filter(user, obj), defaults={"active": False}
    )


def auto_follow(user, obj):
    """Follow what one creates, writes or discusses, unless one chose to unfollow it."""
    if not user.is_authenticated or not can_view(user, obj):
        return
    Subscription.objects.get_or_create(**_subscription_filter(user, obj))


# Stars


def can_star(user, version):
    return (
        user.is_authenticated
        and user.is_active
        and version.is_published
        and not version.is_hidden
        and can_view(user, version)
    )


def star(user, version):
    if not can_star(user, version):
        return None
    return Star.objects.get_or_create(user=user, version=version)[0]


def unstar(user, version):
    if user.is_authenticated:
        Star.objects.filter(user=user, version=version).delete()


def has_starred(user, version):
    return user.is_authenticated and Star.objects.filter(user=user, version=version).exists()


def delete_personal_activity(user):
    """What a deleted account leaves behind is anonymized; its notifications, subscriptions and
    stars are personal choices, and are deleted."""
    Notification.objects.filter(recipient=user).delete()
    Subscription.objects.filter(user=user).delete()
    Star.objects.filter(user=user).delete()
