from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.test import TestCase

from accounts.roles import (
    ADMINISTRATOR,
    CONTRIBUTOR,
    REVIEWER,
    ROLE_PERMISSIONS,
    is_administrator,
    is_reviewer,
    role_labels,
    sync_roles,
)

from .factories import make_user


class RoleTests(TestCase):
    def test_role_groups_exist_after_migrate(self):
        names = set(Group.objects.values_list("name", flat=True))
        self.assertLessEqual(set(ROLE_PERMISSIONS), names)

    def test_groups_have_exactly_the_declared_permissions(self):
        for role, labels in ROLE_PERMISSIONS.items():
            with self.subTest(role=role):
                permissions = Group.objects.get(name=role).permissions.select_related(
                    "content_type"
                )
                granted = {f"{p.content_type.app_label}.{p.codename}" for p in permissions}
                self.assertEqual(granted, set(labels))

    def test_sync_removes_permissions_granted_by_hand(self):
        group = Group.objects.get(name=CONTRIBUTOR)
        group.permissions.add(Permission.objects.get(codename="delete_user"))
        sync_roles()
        self.assertFalse(group.permissions.filter(codename="delete_user").exists())

    def test_role_helpers(self):
        contributor = make_user(email="a@example.org", role=CONTRIBUTOR)
        reviewer = make_user(email="b@example.org", role=REVIEWER)
        administrator = make_user(email="c@example.org", role=ADMINISTRATOR)
        self.assertFalse(is_reviewer(contributor))
        self.assertTrue(is_reviewer(reviewer))
        self.assertFalse(is_administrator(reviewer))
        self.assertTrue(is_reviewer(administrator))
        self.assertTrue(is_administrator(administrator))
        self.assertFalse(is_reviewer(AnonymousUser()))

    def test_inactive_users_lose_their_role(self):
        reviewer = make_user(role=REVIEWER, is_active=False)
        self.assertFalse(is_reviewer(reviewer))

    def test_role_labels(self):
        user = make_user(role=REVIEWER)
        user.groups.add(Group.objects.get(name=CONTRIBUTOR))
        self.assertEqual([str(label) for label in role_labels(user)], ["contributeur", "relecteur"])
