from django.urls import reverse

from phraseology.completeness import mark_reviewed
from phraseology.dashboards import annotator_summary, public_figures, reviewer_queue
from phraseology.services import propose_unit

from .test_frequency import AnalysedCorpusTestCase


class DashboardTests(AnalysedCorpusTestCase):
    def test_public_figures_leave_drafts_out(self):
        figures = public_figures()
        self.assertEqual(figures["units_total"], 0)
        self.assertEqual(sum(figures["attestations"].values()), 0)
        propose_unit(self.unit, self.author)
        mark_reviewed(self.passage, self.reviewer)
        figures = public_figures()
        self.assertEqual(figures["units_total"], 1)
        self.assertEqual(sum(figures["attestations"].values()), 1)
        self.assertEqual((figures["reviewed"], figures["core_passages"]), (1, 3))
        response = self.client.get(reverse("phraseology:figures"))
        self.assertContains(response, "1 / 3")

    def test_the_annotator_sees_what_they_added(self):
        summary = annotator_summary(self.author)
        self.assertEqual(len(summary["attestations"]), 1)
        self.assertEqual(annotator_summary(self.other)["attestations"], [])
        url = reverse("phraseology:annotator")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.author)
        response = self.client.get(url)
        self.assertContains(response, self.unit.reference_form)

    def test_the_reviewer_queue_groups_proposed_attestations_by_passage(self):
        propose_unit(self.unit, self.author)
        queue = reviewer_queue()
        self.assertEqual(queue["proposed_total"], 1)
        (group,) = queue["groups"]
        url = reverse("phraseology:reviewer")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.reviewer)
        response = self.client.get(url)
        self.assertContains(response, f">{group['passage'].citation}</a>")
        self.assertContains(response, "annoter=1")


class ReviewInReadingTests(AnalysedCorpusTestCase):
    def test_a_reviewer_declares_a_passage_from_the_reading(self):
        work = self.passage.edition.work
        reading = reverse("corpus:reading", args=[work.cts_id])
        self.client.force_login(self.other)
        response = self.client.get(reading, {"annoter": "1"})
        self.assertContains(response, "pas encore relu")
        self.assertNotContains(response, "déclarer entièrement relu")
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reading, {"annoter": "1"}), "déclarer entièrement relu")
        mark_reviewed(self.passage, self.reviewer)
        response = self.client.get(reading, {"annoter": "1"})
        self.assertContains(response, "is-reviewed")
        self.assertContains(response, "retirer la déclaration")
        self.assertNotContains(self.client.get(reading), "is-reviewed")
        response = self.client.get(reverse("corpus:work", args=[work.cts_id]))
        self.assertContains(response, "1 / 3")
