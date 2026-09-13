from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from accounts.models import validate_orcid
from accounts.roles import CONTRIBUTOR
from accounts.services import anonymize_user

from .factories import PASSWORD, make_user

User = get_user_model()


class UserModelTests(TestCase):
    def test_project_uses_the_custom_user_model(self):
        self.assertEqual(User._meta.label, "accounts.User")

    def test_create_user_with_email_and_password(self):
        user = make_user()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.is_staff)

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password=PASSWORD, display_name="Nemo")

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.org", password=PASSWORD, display_name="Admin"
        )
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_login_ignores_the_case_of_the_email(self):
        make_user()
        self.assertIsNotNone(authenticate(username="Cicero@Example.org", password=PASSWORD))

    def test_email_is_unique_whatever_the_case(self):
        make_user()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user(email="CICERO@example.org")

    def test_public_name_never_shows_the_email(self):
        user = make_user()
        self.assertEqual(str(user), "Cicero")
        anonymize_user(user)
        self.assertEqual(str(user), "Contributeur anonyme")


class OrcidValidatorTests(SimpleTestCase):
    def test_accepts_valid_identifiers(self):
        for value in ("0000-0002-1825-0097", "0000-0002-1694-233X"):
            with self.subTest(value=value):
                validate_orcid(value)

    def test_rejects_badly_written_identifiers(self):
        for value in (
            "0000000218250097",
            "0000-0002-1825-009",
            "https://orcid.org/0000-0002-1825-0097",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_orcid(value)

    def test_rejects_a_wrong_check_character(self):
        with self.assertRaises(ValidationError):
            validate_orcid("0000-0002-1825-0098")


class AnonymizeUserTests(TestCase):
    def test_personal_data_is_erased_but_the_account_row_stays(self):
        user = make_user(orcid="0000-0002-1825-0097", role=CONTRIBUTOR)
        anonymize_user(user)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "")
        self.assertEqual(user.orcid, "")
        self.assertNotIn("cicero", user.email)
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.anonymized_at)
        self.assertFalse(user.groups.exists())
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
