from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.limits import (
    ContributionLimitReached,
    check_can_contribute,
    contributions_today,
    validate_no_links,
)
from accounts.roles import REVIEWER
from moderation.models import Revision

from .factories import make_user


def record_revision(user, when=None, action=Revision.Action.CREATE):
    return Revision.objects.create(
        content_type=ContentType.objects.get_for_model(user),
        object_id=user.pk,
        author=user,
        action=action,
        after={},
        created_at=when or timezone.now(),
    )


@override_settings(NEW_ACCOUNT_DAILY_LIMIT=2)
class DailyLimitTests(TestCase):
    def test_new_account_is_stopped_at_the_limit(self):
        user = make_user()
        record_revision(user)
        check_can_contribute(user)
        record_revision(user)
        with self.assertRaises(ContributionLimitReached):
            check_can_contribute(user)

    def test_only_creations_count(self):
        user = make_user()
        record_revision(user, action=Revision.Action.UPDATE)
        record_revision(user, action=Revision.Action.REVERT)
        record_revision(user, action=Revision.Action.UPDATE)
        self.assertEqual(contributions_today(user), 0)

    def test_uncounted_contributions_are_allowed_at_the_limit(self):
        user = make_user()
        record_revision(user)
        record_revision(user)
        check_can_contribute(user, counted=False)
        with self.assertRaises(PermissionDenied):
            check_can_contribute(make_user(email="inactive@example.org", is_active=False), False)

    def test_contributions_of_previous_days_do_not_count(self):
        user = make_user()
        for _index in range(3):
            record_revision(user, timezone.now() - timedelta(days=1))
        self.assertEqual(contributions_today(user), 0)
        check_can_contribute(user)

    def test_confirmed_accounts_and_reviewers_are_not_limited(self):
        confirmed = make_user(email="confirmed@example.org", is_confirmed=True)
        reviewer = make_user(email="reviewer@example.org", role=REVIEWER)
        for user in (confirmed, reviewer):
            with self.subTest(user=user.email):
                record_revision(user)
                record_revision(user)
                check_can_contribute(user)

    def test_anonymous_and_inactive_users_cannot_contribute(self):
        with self.assertRaises(PermissionDenied):
            check_can_contribute(AnonymousUser())
        with self.assertRaises(PermissionDenied):
            check_can_contribute(make_user(is_active=False))


class NoLinksValidatorTests(SimpleTestCase):
    def test_links_are_refused(self):
        for text in ("https://example.org", "voir http://example.fr", "www.example.org"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                validate_no_links(text)

    def test_ordinary_text_is_accepted(self):
        for text in ("Cic. Off. 1, 23", "consilium capere : cf. Liv. 1.23.4", "quid multa?", ""):
            with self.subTest(text=text):
                validate_no_links(text)
