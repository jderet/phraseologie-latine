from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.roles import ADMINISTRATOR, CONTRIBUTOR
from moderation.models import Report

from .factories import make_user

NEW_PASSWORD = {"new_password1": "Arpinum-106-av", "new_password2": "Arpinum-106-av"}


class DashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_user("admin@example.org", role=ADMINISTRATOR, display_name="Tiro")
        self.member = make_user("atticus@example.org", role=CONTRIBUTOR, display_name="Atticus")

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_contributor_is_refused(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 403)
        url = reverse("accounts:dashboard_set_password", args=[self.admin.pk])
        self.assertEqual(self.client.post(url, NEW_PASSWORD).status_code, 403)
        self.assertTrue(
            self.admin.__class__.objects.get(pk=self.admin.pk).check_password("Tusculum-45")
        )

    def test_administrator_sees_figures_queues_and_accounts(self):
        Report.objects.create(content_object=self.member, author=self.member, reason="spam")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "atticus@example.org")
        self.assertEqual(response.context["figures"]["active_users"], 2)
        self.assertEqual(response.context["queues"]["reports"], 1)
        self.assertContains(response, reverse("accounts:dashboard"))  # header link

    def test_search_filters_accounts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:dashboard"), {"q": "atti"})
        self.assertEqual([user for user, _roles in response.context["rows"]], [self.member])

    def test_administrator_sets_a_new_password(self):
        self.client.force_login(self.admin)
        url = reverse("accounts:dashboard_set_password", args=[self.member.pk])
        self.assertContains(self.client.get(url), "atticus@example.org")
        response = self.client.post(url, NEW_PASSWORD)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("Arpinum-106-av"))

    def test_administrator_sends_a_reset_link(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("accounts:dashboard_reset_link", args=[self.member.pk]))
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertEqual(mail.outbox[0].to, ["atticus@example.org"])
