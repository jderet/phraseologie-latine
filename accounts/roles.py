"""Platform roles, stored as Django groups.

The permissions of every role are declared here and only here: groups are rebuilt from
this mapping after each ``migrate``, so a permission granted by hand in the admin does
not survive the next migration. Each application adds the permissions of its models to
this mapping when it arrives.
"""

from django.contrib.auth.models import Group, Permission
from django.db import DEFAULT_DB_ALIAS
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

CONTRIBUTOR = "contributor"
REVIEWER = "reviewer"
ADMINISTRATOR = "administrator"

ROLE_LABELS = {
    CONTRIBUTOR: _("contributeur"),
    REVIEWER: _("relecteur"),
    ADMINISTRATOR: _("administrateur"),
}

# Permissions are written "app_label.codename".
ROLE_PERMISSIONS = {
    CONTRIBUTOR: [],
    REVIEWER: [
        "moderation.view_report",
        "moderation.view_revision",
    ],
    ADMINISTRATOR: [
        "accounts.view_user",
        "accounts.change_user",
        "moderation.view_report",
        "moderation.view_revision",
    ],
}


def sync_roles(sender=None, using=DEFAULT_DB_ALIAS, **kwargs):
    """Create the role groups and give each exactly its declared permissions.

    Connected to ``post_migrate``, which is sent once per application: permissions of
    applications migrated later are missing on early calls and set on the last ones.
    """
    for name, labels in ROLE_PERMISSIONS.items():
        group, _created = Group.objects.using(using).get_or_create(name=name)
        query = Q(pk__in=[])
        for label in labels:
            app_label, codename = label.split(".", 1)
            query |= Q(content_type__app_label=app_label, codename=codename)
        group.permissions.set(Permission.objects.using(using).filter(query))


def has_role(user, *roles):
    """Return True when an active user belongs to one of the roles; superusers have all."""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def is_reviewer(user):
    """Reviewers and administrators validate content and handle reports."""
    return has_role(user, REVIEWER, ADMINISTRATOR)


def is_administrator(user):
    return has_role(user, ADMINISTRATOR)


def role_labels(user):
    """Translated labels of the user's roles, in hierarchy order."""
    names = set(user.groups.values_list("name", flat=True))
    return [label for name, label in ROLE_LABELS.items() if name in names]
