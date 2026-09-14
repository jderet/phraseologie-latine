from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from accounts.services import anonymize_user, purge_pending_signups
from moderation.tests.base import ModerationTestCase

from .factories import make_user


def age(user, days):
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=days))


# Deleting a user inspects every content table, including the test-only one of moderation.
@override_settings(PENDING_SIGNUP_RETENTION_DAYS=7)
class PurgePendingSignupsTests(ModerationTestCase):
    def test_deletes_registrations_never_activated_after_the_retention_period(self):
        old = make_user(email="old@example.org", is_active=False)
        age(old, days=8)
        recent = make_user(email="recent@example.org", is_active=False)
        age(recent, days=6)

        self.assertEqual(purge_pending_signups(), 1)
        self.assertFalse(User.objects.filter(pk=old.pk).exists())
        self.assertTrue(User.objects.filter(pk=recent.pk).exists())

    def test_keeps_accounts_that_were_used(self):
        suspended = make_user(email="suspended@example.org", is_active=False)
        User.objects.filter(pk=suspended.pk).update(last_login=timezone.now())
        anonymized = make_user(email="gone@example.org")
        anonymize_user(anonymized)
        kept = [self.owner, suspended, anonymized]
        for user in kept:
            age(user, days=30)

        self.assertEqual(purge_pending_signups(), 0)
        self.assertEqual(User.objects.filter(pk__in=[user.pk for user in kept]).count(), 3)

    def test_command_reports_the_number_of_deleted_registrations(self):
        old = make_user(email="old@example.org", is_active=False)
        age(old, days=8)
        out = StringIO()
        call_command("purge_pending_signups", stdout=out)
        self.assertIn(": 1", out.getvalue())
        self.assertFalse(User.objects.filter(pk=old.pk).exists())
