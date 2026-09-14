from django.urls import reverse

from phraseology.models import Attestation, Unit
from phraseology.services import propose_unit

from .factories import set_status
from .test_validation import ValidationTestCase


class StatusPagesTests(ValidationTestCase):
    def url(self, name, unit=None):
        return reverse(f"phraseology:{name}", args=[(unit or self.unit).pk])

    def test_the_creator_sees_what_is_missing_and_proposes(self):
        self.client.force_login(self.author)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "Une fiche n’est validée qu’avec tous ses champs")
        self.assertContains(page, "un renvoi bibliographique")
        self.assertContains(page, "Proposer la fiche")
        self.assertRedirects(
            self.client.post(self.url("unit_propose")), self.unit.get_absolute_url()
        )
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.PROPOSED)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url("unit_propose")).status_code, 403)

    def test_a_reviewer_validates_a_complete_unit(self):
        propose_unit(self.unit, self.author)
        self.client.force_login(self.reviewer)
        self.assertNotContains(self.client.get(self.unit.get_absolute_url()), "Valider la fiche")
        self.complete(self.unit)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "Tous les champs sont remplis")
        self.assertContains(page, "Valider la fiche")
        self.client.post(self.url("unit_validate"))
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.VALIDATED)
        self.assertContains(self.client.get(self.unit.get_absolute_url()), "Validée par Titus")

    def test_the_frequency_is_shown_and_computed_again(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        self.unit.save()
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.unit.get_absolute_url()), "pas encore calculée")
        response = self.client.post(self.url("unit_frequency"), follow=True)
        self.assertContains(response, "4 occurrences repérées automatiquement.")
        self.assertContains(
            response, "4 occurrences du schéma repérées automatiquement, dont 3 dans le noyau"
        )
        self.assertContains(response, "Sénèque")

    def test_contest_and_resolution_pages(self):
        self.validated()
        self.client.force_login(self.other)
        response = self.client.post(self.url("unit_contest"), {"argument": "Douteux."})
        self.assertRedirects(response, f"{self.unit.get_absolute_url()}#discussion")
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "Cette fiche est contestée")
        self.assertContains(page, "Douteux.")
        self.assertEqual(
            self.client.post(
                self.url("unit_resolve"), {"status": "validated", "reason": "Non."}
            ).status_code,
            403,
        )
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(self.unit.get_absolute_url()), "Lever la contestation")
        self.client.post(self.url("unit_resolve"), {"status": "validated", "reason": "Défendable."})
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, Unit.Status.VALIDATED)


class AttestationPagesTests(ValidationTestCase):
    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        self.attestation = self.unit.attestations.get()

    def test_review_by_reviewers_only(self):
        url = reverse("phraseology:attestation_review", args=[self.attestation.pk])
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.unit.get_absolute_url()), 'value="valider"')
        self.assertEqual(self.client.post(url, {"decision": "valider"}).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(self.unit.get_absolute_url()), 'value="valider"')
        self.assertEqual(self.client.post(url, {"decision": "autre"}).status_code, 400)
        self.client.post(url, {"decision": "valider"})
        self.attestation.refresh_from_db()
        self.assertEqual(self.attestation.status, Attestation.Status.VALIDATED)

    def test_choosing_an_example(self):
        url = reverse("phraseology:attestation_example", args=[self.attestation.pk])
        self.client.force_login(self.other)
        self.client.post(url, {"exemple": "1"})
        self.attestation.refresh_from_db()
        self.assertTrue(self.attestation.is_example)
        self.assertContains(
            self.client.get(self.unit.get_absolute_url()), "ne plus montrer en exemple"
        )

    def test_occurrences_of_the_schema_are_offered(self):
        Unit.objects.filter(pk=self.unit.pk).update(schema="capio -obj|nsubj:pass-> consilium")
        self.client.force_login(self.other)
        url = reverse("phraseology:attestation_add", args=[self.unit.pk])
        response = self.client.get(url)
        self.assertContains(response, "3 occurrences repérées automatiquement")
        self.assertContains(response, "déjà attestée")
        consilia, capiunt = self.more_words[:2]
        self.assertContains(response, f'name="occurrence" value="{consilia.pk},{capiunt.pk}"')
        self.assertContains(self.client.get(url, {"occurrences": "tout"}), "4 occurrences repérées")
        self.client.post(
            url, {"occurrence": [f"{consilia.pk},{capiunt.pk}"], "sense": "", "realization": ""}
        )
        added = self.unit.attestations.get(passage=self.second_passage)
        self.assertEqual(added.origin, Attestation.Origin.QUERY)
