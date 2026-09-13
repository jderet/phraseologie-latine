from django.template import Context, Template
from django.urls import reverse

from moderation.models import Report
from moderation.registry import history_url, report_url
from moderation.services import create_report, save_with_revision

from .base import ModerationTestCase
from .models import ModerationTestNote


class HistoryViewTests(ModerationTestCase):
    def setUp(self):
        self.note = ModerationTestNote(author=self.owner, text="consilium capere")
        self.first = save_with_revision(self.note, self.owner)
        self.note.text = "consilium cepit"
        save_with_revision(self.note, self.owner)
        self.url = history_url(self.note)

    def test_history_of_visible_content_is_public(self):
        response = self.client.get(self.url)
        self.assertContains(response, "consilium capere")
        self.assertContains(response, "consilium cepit")
        self.assertNotContains(response, "Rétablir cette version")

    def test_history_of_a_draft_is_private(self):
        draft = ModerationTestNote.objects.create(author=self.owner, text="x", is_draft=True)
        self.assertEqual(self.client.get(history_url(draft)).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(history_url(draft)).status_code, 200)

    def test_unregistered_models_have_no_history_page(self):
        url = reverse("moderation:history", args=["accounts", "user", self.owner.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_reviewer_reverts_from_the_history_page(self):
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(self.url), "Rétablir cette version")
        response = self.client.post(reverse("moderation:revert", args=[self.first.pk]))
        self.assertRedirects(response, self.url)
        self.note.refresh_from_db()
        self.assertEqual(self.note.text, "consilium capere")

    def test_revert_is_refused_to_other_contributors(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("moderation:revert", args=[self.first.pk]))
        self.assertEqual(response.status_code, 403)

    def test_revert_requires_post(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("moderation:revert", args=[self.first.pk]))
        self.assertEqual(response.status_code, 405)


class ReportViewTests(ModerationTestCase):
    def setUp(self):
        self.note = ModerationTestNote.objects.create(author=self.owner, text="x")
        self.url = report_url(self.note)

    def test_login_is_required(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")

    def test_report_is_recorded(self):
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.url), "publicité ou spam")
        response = self.client.post(self.url, {"reason": "spam", "message": "publicité"})
        self.assertRedirects(response, self.note.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(Report.objects.filter(author=self.other, status="open").exists())


class ReportQueueTests(ModerationTestCase):
    def setUp(self):
        self.note = ModerationTestNote.objects.create(author=self.owner, text="texte signalé")
        self.report, _created = create_report(
            self.other, self.note, Report.Reason.ILLEGAL, "illicite"
        )

    def test_queue_is_for_reviewers(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("moderation:report_queue")).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse("moderation:report_queue")), "texte signalé")

    def test_reviewer_hides_reported_content(self):
        self.client.force_login(self.reviewer)
        response = self.client.post(
            reverse("moderation:handle_report", args=[self.report.pk]),
            {"decision": "hide", "resolution": "retiré"},
        )
        self.assertRedirects(response, reverse("moderation:report_queue"))
        self.note.refresh_from_db()
        self.report.refresh_from_db()
        self.assertTrue(self.note.is_hidden)
        self.assertEqual(self.report.status, Report.Status.HANDLED)

    def test_contributors_cannot_handle_reports(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("moderation:handle_report", args=[self.report.pk]), {"decision": "rejected"}
        )
        self.assertEqual(response.status_code, 403)


class ModerationLinksTagTests(ModerationTestCase):
    def test_links_to_history_and_report(self):
        note = ModerationTestNote.objects.create(author=self.owner, text="x")
        template = Template("{% load moderation_tags %}{% moderation_links note %}")
        html = template.render(Context({"note": note, "user": self.other}))
        self.assertIn(history_url(note), html)
        self.assertIn(report_url(note), html)
