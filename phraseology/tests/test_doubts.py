from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from corpus.models import Token
from moderation.models import Comment
from phraseology.models import Attestation, AttestationDoubt
from phraseology.services import (
    contest_attestation,
    decide_doubts,
    doubt_attestation,
    propose_unit,
    record_automatic_attestations,
    resolve_attestation_contest,
)

from .test_frequency import AnalysedCorpusTestCase


class DoubtTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        self.unit.refresh_from_db()
        self.attestation = self.unit.attestations.get()
        self.url = reverse("phraseology:attestation", args=[self.attestation.pk])


class DoubtServiceTests(DoubtTestCase):
    def test_a_doubt_is_settled_by_a_reviewer(self):
        doubt = doubt_attestation(
            self.attestation, self.other, "Ici consilium désigne une assemblée."
        )
        with self.assertRaises(ValidationError):
            doubt_attestation(self.attestation, self.other, "Encore.")
        with self.assertRaises(PermissionDenied):
            decide_doubts(self.attestation, self.other, reject=False)
        decide_doubts(self.attestation, self.reviewer, reject=True)
        doubt.refresh_from_db()
        self.attestation.refresh_from_db()
        self.assertEqual(
            (doubt.status, doubt.decided_by), (AttestationDoubt.Status.REJECTED, self.reviewer)
        )
        self.assertEqual(self.attestation.status, Attestation.Status.REJECTED)
        with self.assertRaises(ValidationError):
            doubt_attestation(self.attestation, self.author, "Déjà rejetée.")

    def test_a_kept_attestation_stays_as_it_is(self):
        doubt = doubt_attestation(self.attestation, self.other, "Douteux.")
        decide_doubts(self.attestation, self.reviewer, reject=False)
        doubt.refresh_from_db()
        self.attestation.refresh_from_db()
        self.assertEqual(doubt.status, AttestationDoubt.Status.KEPT)
        self.assertEqual(self.attestation.status, Attestation.Status.PROPOSED)
        with self.assertRaises(ValidationError):
            decide_doubts(self.attestation, self.reviewer, reject=False)


class ContestServiceTests(DoubtTestCase):
    def test_a_contest_opens_the_discussion_and_a_reviewer_settles_it(self):
        contest_attestation(self.attestation, self.other, "Ce n’est pas une décision.")
        self.attestation.refresh_from_db()
        self.assertTrue(self.attestation.is_contested)
        self.assertEqual(Comment.objects.for_object(self.attestation).count(), 1)
        with self.assertRaises(ValidationError):
            contest_attestation(self.attestation, self.author, "Encore.")
        with self.assertRaises(PermissionDenied):
            resolve_attestation_contest(self.attestation, self.other, "keep", "Non.")
        resolve_attestation_contest(self.attestation, self.reviewer, "validate", "C’est l’unité.")
        self.attestation.refresh_from_db()
        self.assertFalse(self.attestation.is_contested)
        self.assertEqual(self.attestation.status, Attestation.Status.VALIDATED)
        self.assertEqual(Comment.objects.for_object(self.attestation).count(), 2)

    def test_outside_the_core_a_contested_automatic_attestation_is_never_validated(self):
        outside = Token.objects.filter(edition__work__is_core=False).order_by("position")
        (found,) = record_automatic_attestations(
            self.unit, [tuple(token.pk for token in outside)], self.author
        )
        contest_attestation(found, self.other, "Douteux.")
        with self.assertRaises(ValidationError):
            resolve_attestation_contest(found, self.reviewer, "validate", "Pourtant.")
        found.refresh_from_db()
        self.assertTrue(found.is_contested)
        resolve_attestation_contest(found, self.reviewer, "reject", "Ce n’est pas l’unité.")
        found.refresh_from_db()
        self.assertEqual(found.status, Attestation.Status.REJECTED)


class AttestationPageTests(DoubtTestCase):
    def test_the_page_of_an_attestation(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertContains(response, "Personne n’a signalé cette attestation comme douteuse.")
        self.assertNotContains(response, "Signaler comme douteuse")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.url), "Signaler comme douteuse")

    def test_doubts_and_contest_through_the_page(self):
        self.client.force_login(self.other)
        doubt = reverse("phraseology:attestation_doubt", args=[self.attestation.pk])
        self.assertRedirects(
            self.client.post(doubt, {"reason": "Assemblée."}), f"{self.url}#doutes"
        )
        contest = reverse("phraseology:attestation_contest", args=[self.attestation.pk])
        response = self.client.post(contest, {"argument": "Pas une décision."})
        self.assertRedirects(response, f"{self.url}#contestation")
        page = self.client.get(self.url)
        self.assertContains(page, "Assemblée.")
        self.assertContains(page, "Pas une décision.")
        self.assertContains(page, "L’attestation est juste")
        self.client.force_login(self.reviewer)
        decide = reverse("phraseology:attestation_doubts_decide", args=[self.attestation.pk])
        self.assertRedirects(
            self.client.post(decide, {"decision": "maintenir"}), f"{self.url}#doutes"
        )
        resolve = reverse("phraseology:attestation_contest_resolve", args=[self.attestation.pk])
        data = {"decision": "keep", "reason": "L’unité est bien là."}
        self.assertRedirects(self.client.post(resolve, data), f"{self.url}#contestation")
        self.attestation.refresh_from_db()
        self.assertFalse(self.attestation.is_contested)
        self.assertEqual(self.attestation.doubts.get().status, AttestationDoubt.Status.KEPT)
