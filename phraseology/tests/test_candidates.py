from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from phraseology.candidates import extract_candidates, pair_counts
from phraseology.models import Attestation, Candidate, Unit
from phraseology.services import (
    create_unit_from_candidate,
    reject_candidate,
    reopen_candidate,
    retain_candidate,
)

from .factories import evidence, set_status
from .test_frequency import AnalysedCorpusTestCase


class CandidateTestCase(AnalysedCorpusTestCase):
    def extract(self, **options):
        return extract_candidates(self.layer, **({"min_frequency": 1, "min_score": 0} | options))

    def candidate(self):
        return Candidate.objects.get(head="capio", relation="obj", dependent="consilium")


class ExtractionTests(CandidateTestCase):
    def test_pairs_of_the_core(self):
        pairs = {row[:3]: row[3:] for row in pair_counts(self.layer, min_frequency=1)}
        self.assertEqual(pairs[("capio", "obj", "consilium")], (3, 3, 3, 3))
        self.assertEqual(pairs[("consilium", "amod", "bonus")], (1, 1, 1, 1))
        everywhere = pair_counts(self.layer, core_only=False, min_frequency=1)
        self.assertIn(("capio", "obj", "consilium", 4, 4, 4, 4), everywhere)

    def test_decisions_survive_a_new_extraction(self):
        self.assertEqual(self.extract(), {"created": 2, "updated": 0, "removed": 0})
        candidate = self.candidate()
        self.assertEqual(candidate.frequency, 3)
        self.assertEqual(candidate.schema, "capio -obj|nsubj:pass-> consilium")
        self.assertIn("LatinCy test 1.0", candidate.corpus_version)
        reject_candidate(candidate, self.other)
        self.assertEqual(self.extract(min_frequency=2), {"created": 0, "updated": 1, "removed": 1})
        self.assertEqual(self.candidate().status, Candidate.Status.REJECTED)
        self.assertFalse(Candidate.objects.filter(relation="amod").exists())

    def test_the_command(self):
        output = StringIO()
        call_command("extract_candidates", "--min-frequency=1", "--min-score=0", stdout=output)
        self.assertIn("2 nouveaux", output.getvalue())


class DecisionTests(CandidateTestCase):
    def setUp(self):
        super().setUp()
        self.extract()

    def test_rejection_and_reopening(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        candidate = self.candidate()
        with self.assertRaises(PermissionDenied):
            reject_candidate(candidate, newcomer)
        reject_candidate(candidate, self.other)
        candidate.refresh_from_db()
        self.assertEqual((candidate.status, candidate.decided_by), ("rejected", self.other))
        with self.assertRaises(ValidationError):
            reject_candidate(candidate, self.other)
        with self.assertRaises(PermissionDenied):
            reopen_candidate(candidate, self.other)
        reopen_candidate(candidate, self.reviewer)
        candidate.refresh_from_db()
        self.assertEqual((candidate.status, candidate.decided_by), ("pending", None))

    def test_a_unit_made_from_a_candidate(self):
        unit = create_unit_from_candidate(
            self.candidate(),
            self.other,
            Unit(reference_form="consilium capere"),
            "décider",
            [evidence(*self.more_words[:2])],
        )
        candidate = self.candidate()
        self.assertEqual((candidate.status, candidate.unit), ("retained", unit))
        self.assertEqual(unit.schema, "capio -obj|nsubj:pass-> consilium")
        self.assertEqual(unit.attestations.get().origin, Attestation.Origin.CANDIDATE)
        self.assertEqual(unit.frequency.total, 4)

    def test_retaining_for_a_visible_unit_only(self):
        with self.assertRaises(PermissionDenied):
            retain_candidate(self.candidate(), self.other, self.unit)
        retain_candidate(self.candidate(), self.author, self.unit)
        self.assertEqual(self.candidate().unit, self.unit)


class CandidatePagesTests(CandidateTestCase):
    def setUp(self):
        super().setUp()
        self.extract()
        self.list_url = reverse("phraseology:candidate_list")

    def test_the_queue(self):
        response = self.client.get(self.list_url)
        self.assertContains(response, "capio —obj→ consilium")
        self.assertNotContains(response, "Rejeter")
        self.client.force_login(self.other)
        response = self.client.get(self.list_url, {"q": "bon"})
        self.assertContains(response, "consilium —amod→ bonus")
        self.assertNotContains(response, "capio —obj→ consilium")
        url = reverse("phraseology:candidate_reject", args=[self.candidate().pk])
        response = self.client.post(url, {"next": "/candidats/?q=cap"})
        self.assertRedirects(response, "/candidats/?q=cap", fetch_redirect_response=False)
        response = self.client.post(url, {"next": "https://example.org/"})
        self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
        rejected = self.client.get(self.list_url, {"statut": "rejected"})
        self.assertContains(rejected, "capio —obj→ consilium")

    def test_creating_a_unit_from_a_candidate(self):
        url = self.candidate().get_absolute_url()
        response = self.client.get(url)
        self.assertContains(response, "3 occurrences repérées automatiquement")
        self.assertContains(response, "Connectez-vous pour retenir ou rejeter")
        self.assertEqual(self.client.post(url, {}).status_code, 302)
        self.client.force_login(self.other)
        consilia, capiunt = self.more_words[:2]
        value = f"{consilia.pk},{capiunt.pk}"
        self.assertContains(self.client.get(url), f'name="attestation" value="{value}"')
        data = {"reference_form": "consilium capere", "definition": "décider"}
        response = self.client.post(url, data | {"attestation": [value]})
        unit = Unit.objects.get(created_by=self.other)
        self.assertRedirects(response, unit.get_absolute_url())
        self.assertContains(self.client.get(url), "Retenu")

    def test_retaining_for_an_existing_unit(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        Unit.objects.filter(pk=self.unit.pk).update(schema="capio -obj|nsubj:pass-> consilium")
        candidate = self.candidate()
        self.client.force_login(self.other)
        self.assertContains(
            self.client.get(candidate.get_absolute_url()), "Fiches qui ont déjà ce schéma"
        )
        url = reverse("phraseology:candidate_attach", args=[candidate.pk])
        response = self.client.post(url, {"unit": self.unit.pk})
        self.assertRedirects(response, self.unit.get_absolute_url())
        self.assertEqual(self.candidate().unit, self.unit)
        self.client.force_login(self.reviewer)
        self.client.post(reverse("phraseology:candidate_reopen", args=[candidate.pk]))
        self.assertEqual(self.candidate().status, Candidate.Status.PENDING)
