from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.throttle import ACTIVATION_EMAILS, LOGIN_FAILURES, RESET_EMAILS

from .factories import PASSWORD, make_user
from .test_signup import SIGNUP


class ThrottleTestCase(TestCase):
    def setUp(self):
        cache.clear()


class LoginThrottleTests(ThrottleTestCase):
    def login(self, password, email="cicero@example.org", url=None):
        url = url or reverse("accounts:login")
        return self.client.post(url, {"username": email, "password": password})

    def fail(self, times, **kwargs):
        for _attempt in range(times):
            self.login("wrong-password", **kwargs)

    def test_the_password_is_no_longer_checked_after_five_failures(self):
        make_user()
        self.fail(LOGIN_FAILURES.limit)
        response = self.login(PASSWORD)
        self.assertContains(response, "Trop de tentatives de connexion pour ce compte")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_limit_counts_one_address_only(self):
        make_user()
        make_user(email="atticus@example.org", display_name="Atticus")
        self.fail(LOGIN_FAILURES.limit)
        self.assertEqual(self.login(PASSWORD, email="atticus@example.org").status_code, 302)

    def test_a_successful_login_clears_the_failures(self):
        make_user()
        self.fail(LOGIN_FAILURES.limit - 1)
        self.assertEqual(self.login(PASSWORD).status_code, 302)
        self.client.logout()
        self.fail(LOGIN_FAILURES.limit - 1)
        self.assertEqual(self.login(PASSWORD).status_code, 302)

    def test_unknown_addresses_are_limited_the_same_way(self):
        self.fail(LOGIN_FAILURES.limit, email="nobody@example.org")
        response = self.login("wrong-password", email="nobody@example.org")
        self.assertContains(response, "Trop de tentatives de connexion pour ce compte")

    def test_the_admin_login_is_limited_too(self):
        make_user(is_staff=True, is_superuser=True)
        url = reverse("admin:login")
        self.fail(LOGIN_FAILURES.limit, url=url)
        response = self.login(PASSWORD, url=url)
        self.assertContains(response, "Trop de tentatives de connexion pour ce compte")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_counters_do_not_store_the_address(self):
        self.assertNotIn("cicero", LOGIN_FAILURES.key("Cicero@example.org"))
        self.assertEqual(
            LOGIN_FAILURES.key("Cicero@example.org"), LOGIN_FAILURES.key(" cicero@example.org")
        )


@override_settings(SIGNUP_SKIP_EMAIL_VERIFICATION=False)
class EmailThrottleTests(ThrottleTestCase):
    def test_signing_up_again_resends_the_link_a_few_times_only(self):
        for _attempt in range(ACTIVATION_EMAILS.limit + 2):
            response = self.client.post(reverse("accounts:signup"), SIGNUP)
            self.assertRedirects(response, reverse("accounts:signup_done"))
        self.assertEqual(len(mail.outbox), ACTIVATION_EMAILS.limit)

    def test_reset_emails_are_limited_and_the_page_answers_the_same(self):
        make_user()
        for _attempt in range(RESET_EMAILS.limit + 2):
            response = self.client.post(
                reverse("accounts:password_reset"), {"email": "cicero@example.org"}
            )
            self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), RESET_EMAILS.limit)
