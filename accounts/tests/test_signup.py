import re

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.checks import check_signup_verification
from accounts.models import User
from accounts.roles import CONTRIBUTOR

from .factories import make_user

SIGNUP = {
    "email": "plinius@example.org",
    "display_name": "Plinius",
    "password1": "Comum-Larius-61",
    "password2": "Comum-Larius-61",
    "is_adult": "on",
}


def activation_path(message):
    return re.search(r"https?://[^/\s]+(/compte/activation/\S+/)", message.body).group(1)


@override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=False)
class SignupTests(TestCase):
    def test_signup_page_renders(self):
        response = self.client.get(reverse("accounts:signup"))
        self.assertContains(response, "Je déclare avoir 18 ans ou plus.")

    def test_signup_page_is_translated(self):
        response = self.client.get(reverse("accounts:signup"), headers={"accept-language": "en"})
        self.assertContains(response, "I declare that I am 18 or older.")

    def test_signup_creates_an_inactive_account_and_sends_the_link(self):
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertRedirects(response, reverse("accounts:signup_done"))
        user = User.objects.get(email="plinius@example.org")
        self.assertFalse(user.is_active)
        self.assertTrue(user.is_adult)
        self.assertIsNotNone(user.adult_declared_at)
        self.assertEqual(user.interface_language, "fr")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["plinius@example.org"])
        self.assertIn("/compte/activation/", mail.outbox[0].body)

    def test_majority_declaration_is_required(self):
        data = {key: value for key, value in SIGNUP.items() if key != "is_adult"}
        response = self.client.post(reverse("accounts:signup"), data)
        self.assertContains(response, "réservée aux personnes majeures")
        self.assertFalse(User.objects.exists())

    def test_email_of_an_existing_account_is_refused(self):
        make_user(email="plinius@example.org")
        response = self.client.post(
            reverse("accounts:signup"), {**SIGNUP, "email": "Plinius@example.org"}
        )
        self.assertContains(response, "Un compte existe déjà")
        self.assertEqual(len(mail.outbox), 0)

    def test_signing_up_again_replaces_a_pending_registration(self):
        self.client.post(reverse("accounts:signup"), SIGNUP)
        first_link = activation_path(mail.outbox[0])
        self.client.post(reverse("accounts:signup"), {**SIGNUP, "display_name": "C. Plinius"})
        self.assertEqual(User.objects.get().display_name, "C. Plinius")
        self.assertEqual(self.client.get(first_link).status_code, 400)
        self.assertEqual(self.client.get(activation_path(mail.outbox[1])).status_code, 200)


@override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=False)
class ActivationTests(TestCase):
    def setUp(self):
        self.client.post(reverse("accounts:signup"), SIGNUP)
        self.link = activation_path(mail.outbox[0])
        self.user = User.objects.get()

    def test_link_asks_for_confirmation_without_activating(self):
        response = self.client.get(self.link)
        self.assertContains(response, "Activer mon compte")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_confirmation_activates_logs_in_and_grants_the_contributor_role(self):
        response = self.client.post(self.link)
        self.assertRedirects(response, reverse("accounts:account"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.groups.filter(name=CONTRIBUTOR).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_link_works_only_once(self):
        self.client.post(self.link)
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.post(self.link).status_code, 400)

    def test_tampered_links_are_refused(self):
        self.assertEqual(self.client.get(self.link[:-3] + "xx/").status_code, 400)
        self.assertEqual(self.client.get("/compte/activation/zzz/abc/").status_code, 400)

    def test_password_reset_token_cannot_activate(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.post(reverse("accounts:activate", args=[uid, token]))
        self.assertEqual(response.status_code, 400)


class SkipEmailVerificationTests(TestCase):
    @override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=True)
    def test_account_is_active_and_logged_in_at_once(self):
        response = self.client.post(reverse("accounts:signup"), SIGNUP)
        self.assertRedirects(response, reverse("accounts:account"))
        user = User.objects.get(email="plinius@example.org")
        self.assertTrue(user.is_active)
        self.assertTrue(user.groups.filter(name=CONTRIBUTOR).exists())
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=True, DEBUG=False)
    def test_deploy_check_refuses_it_without_debug(self):
        self.assertEqual([e.id for e in check_signup_verification(None)], ["accounts.E001"])

    @override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=True, DEBUG=True)
    def test_deploy_check_allows_it_with_debug(self):
        self.assertEqual(check_signup_verification(None), [])
