from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from phraseology.completeness import (
    mark_reviewed,
    passages_to_review,
    withdraw_review,
    work_progress,
)
from phraseology.models import Attestation, PassageReview
from phraseology.services import propose_unit, review_attestation

from .test_frequency import AnalysedCorpusTestCase


class CompletenessTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.passage.edition.work

    def test_passages_declared_entirely_reviewed(self):
        with self.assertRaises(PermissionDenied):
            mark_reviewed(self.passage, self.other)
        review = mark_reviewed(self.passage, self.reviewer)
        self.assertIn("LatinCy test 1.0", review.corpus_version)
        with self.assertRaises(ValidationError):
            mark_reviewed(self.passage, self.reviewer)
        self.assertNotIn(self.passage, passages_to_review(self.work))
        (row,) = work_progress([self.work])
        self.assertEqual((row["total"], row["reviewed"], row["percent"]), (3, 1, 33))
        withdraw_review(self.passage, self.reviewer)
        self.assertIn(self.passage, passages_to_review(self.work))
        mark_reviewed(self.passage, self.reviewer)
        self.assertEqual(PassageReview.objects.count(), 2)

    def test_the_progress_counts_validated_attestations(self):
        propose_unit(self.unit, self.author)
        attestation = self.unit.attestations.get()
        review_attestation(attestation, self.reviewer, Attestation.Status.VALIDATED)
        (row,) = work_progress([self.work])
        self.assertEqual(row["validated"], 1)

    def test_the_queue_and_the_declaration_through_the_pages(self):
        url = reverse("phraseology:review_queue")
        chosen = {"oeuvre": self.work.cts_id}
        response = self.client.get(url, chosen)
        self.assertContains(response, ">Cic. Off. 1, 1</a>")
        self.assertNotContains(response, "déclarer entièrement relu")
        self.client.force_login(self.reviewer)
        declare = reverse("phraseology:passage_review", args=[self.passage.pk])
        back = f"{url}?oeuvre={self.work.cts_id}"
        response = self.client.post(declare, {"action": "relu", "next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.assertNotContains(self.client.get(url, chosen), ">Cic. Off. 1, 1</a>")
        self.client.post(declare, {"action": "retirer", "next": back})
        self.assertContains(self.client.get(url, chosen), ">Cic. Off. 1, 1</a>")
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(declare, {"action": "relu"}).status_code, 403)
