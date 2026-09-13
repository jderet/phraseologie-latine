from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .factories import PASSWORD, make_user


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user(interface_language="en")

    def test_login_with_email_applies_the_interface_language(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "cicero@example.org", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertEqual(response.cookies["django_language"].value, "en")

    def test_inactive_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("accounts:login"), {"username": "cicero@example.org", "password": PASSWORD}
        )
        self.assertContains(response, "activez d’abord votre compte")

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class AccountPageTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_requires_login(self):
        url = reverse("accounts:account")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")

    def test_update_profile_and_language(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:account"),
            {
                "display_name": "M. Tullius Cicero",
                "orcid": "0000-0002-1825-0097",
                "interface_language": "en",
            },
        )
        self.assertRedirects(response, reverse("accounts:account"), fetch_redirect_response=False)
        self.assertEqual(response.cookies["django_language"].value, "en")
        self.user.refresh_from_db()
        self.assertEqual(self.user.display_name, "M. Tullius Cicero")
        self.assertEqual(self.user.orcid, "0000-0002-1825-0097")

    def test_invalid_orcid_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:account"),
            {"display_name": "Cicero", "orcid": "0000-0002-1825-0098", "interface_language": "fr"},
        )
        self.assertContains(response, "Cet identifiant ORCID n’existe pas")


class ProfilePageTests(TestCase):
    def test_public_profile_shows_the_name_but_not_the_email(self):
        user = make_user(orcid="0000-0002-1825-0097")
        response = self.client.get(reverse("accounts:profile", args=[user.pk]))
        self.assertContains(response, "<h1>Cicero</h1>", html=True)
        self.assertContains(response, "https://orcid.org/0000-0002-1825-0097")
        self.assertNotContains(response, "cicero@example.org")

    def test_inactive_accounts_have_no_public_page(self):
        user = make_user(is_active=False)
        response = self.client.get(reverse("accounts:profile", args=[user.pk]))
        self.assertEqual(response.status_code, 404)


class DeleteAccountTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_wrong_password_keeps_the_account(self):
        response = self.client.post(reverse("accounts:delete"), {"password": "Arpinum"})
        self.assertContains(response, "Mot de passe incorrect")
        self.user.refresh_from_db()
        self.assertIsNone(self.user.anonymized_at)

    def test_deletion_anonymizes_and_logs_out(self):
        response = self.client.post(reverse("accounts:delete"), {"password": PASSWORD})
        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.anonymized_at)
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordResetTests(TestCase):
    def test_reset_email_links_to_the_new_password_page(self):
        make_user()
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "cicero@example.org"}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/compte/mot-de-passe/nouveau/", mail.outbox[0].body)
