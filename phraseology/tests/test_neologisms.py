from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from justifications.models import Evidence
from justifications.services import reference_evidence
from moderation.registry import can_view, uncounted_models
from phraseology.models import Neologism, NeologismEquivalent
from phraseology.permissions import can_edit_neologism
from phraseology.services import (
    add_neologism_evidences,
    create_neologism,
    update_neologism,
    validate_neologism,
    withdraw_neologism_equivalent,
    withdraw_neologism_evidence,
)

from .factories import evidence
from .test_units import PhraseologyTestCase


class NeologismTestCase(PhraseologyTestCase):
    def setUp(self):
        super().setUp()
        self.neologism = create_neologism(
            Neologism(
                form="birota",
                meaning="la bicyclette",
                formation=Neologism.Formation.DERIVATION,
                justification="Formé comme bigae, sur rota.",
                lrl_reference="s. v. birota",
            ),
            self.author,
            NeologismEquivalent(language="fr", expression="vélo"),
            [evidence(*self.words[:2]), reference_evidence(self.grammar, "§ 97")],
        )


class NeologismServicesTests(NeologismTestCase):
    def test_a_neologism_is_public_and_justified(self):
        neologism = self.neologism
        self.assertEqual(neologism.status, Neologism.Status.PROPOSED)
        self.assertTrue(can_view(self.other, neologism))
        self.assertEqual(neologism.equivalents.get().expression, "vélo")
        kinds = sorted(neologism.evidences.values_list("kind", flat=True))
        self.assertEqual(kinds, ["corpus", "grammar"])
        self.assertIn(NeologismEquivalent, uncounted_models())
        self.assertNotIn(Neologism, uncounted_models())

    def test_evidence_has_exactly_one_parent(self):
        attestation = self.neologism.evidences.get(kind="corpus")
        attestation.challenge_id = None
        attestation.justification_id = None
        attestation.save()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Evidence.objects.filter(pk=attestation.pk).update(neologism=None)

    def test_any_active_account_completes_a_neologism(self):
        self.assertTrue(can_edit_neologism(self.other, self.neologism))
        self.neologism.meaning = "la bicyclette, le vélo"
        self.assertEqual(update_neologism(self.neologism, self.other).author, self.other)
        add_neologism_evidences(
            self.neologism, [reference_evidence(self.grammar, "§ 98")], self.other
        )
        self.other.is_active = False
        with self.assertRaises(PermissionDenied):
            update_neologism(self.neologism, self.other)

    def test_a_neologism_keeps_one_equivalent(self):
        with self.assertRaises(ValidationError):
            withdraw_neologism_equivalent(self.neologism.equivalents.get(), self.other)

    def test_withdrawing_evidence(self):
        reference = self.neologism.evidences.get(kind="grammar")
        withdraw_neologism_evidence(reference, self.other)
        reference.refresh_from_db()
        self.assertTrue(reference.is_withdrawn)
        self.assertIsNone(withdraw_neologism_evidence(reference, self.other))

    def test_validation_by_a_reviewer(self):
        with self.assertRaises(PermissionDenied):
            validate_neologism(self.neologism, self.other)
        self.assertEqual(validate_neologism(self.neologism, self.reviewer).comment, "Validation")
        self.neologism.refresh_from_db()
        self.assertEqual(self.neologism.validated_by, self.reviewer)
        self.assertIsNone(validate_neologism(self.neologism, self.reviewer))


class NeologismPagesTests(NeologismTestCase):
    def test_the_lexicon_is_searched_by_latin_or_modern_word(self):
        url = reverse("phraseology:neologism_list")
        self.assertContains(self.client.get(url, {"q": "vélo"}), "birota")
        self.assertContains(self.client.get(url, {"q": "birot"}), "birota")
        self.assertNotContains(self.client.get(url, {"q": "voiture"}), "birota")

    def test_the_detail_page(self):
        response = self.client.get(self.neologism.get_absolute_url())
        self.assertContains(response, "néologisme")
        self.assertContains(response, "s. v. birota")
        self.assertContains(response, "ouvrage sous droits, cité sans extrait")
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertContains(response, "A&amp;G")
        self.assertNotContains(response, "Valider le néologisme")
        self.client.force_login(self.reviewer)
        response = self.client.get(self.neologism.get_absolute_url())
        withdraw = reverse(
            "phraseology:neologism_evidence_withdraw",
            args=[self.neologism.evidences.get(kind="grammar").pk],
        )
        self.assertContains(response, f'action="{withdraw}"')
        self.client.post(reverse("phraseology:neologism_validate", args=[self.neologism.pk]))
        self.neologism.refresh_from_db()
        self.assertEqual(self.neologism.status, Neologism.Status.VALIDATED)

    def test_proposing_a_neologism(self):
        self.client.force_login(self.other)
        url = reverse("phraseology:neologism_create")
        data = {
            "form": "currus  electricus",
            "meaning": "la voiture électrique",
            "formation": "periphrasis",
            "justification": "Périphrase transparente.",
            "lrl_reference": "",
            "language": "fr",
            "expression": "voiture électrique",
            "attestation": [f"{self.more_words[0].pk}"],
            "references-TOTAL_FORMS": "2",
            "references-INITIAL_FORMS": "0",
            "references-MIN_NUM_FORMS": "0",
            "references-MAX_NUM_FORMS": "5",
            "references-0-work": str(self.grammar.pk),
            "references-0-locator": "§ 1",
        }
        response = self.client.post(url, data)
        neologism = Neologism.objects.get(created_by=self.other)
        self.assertRedirects(response, neologism.get_absolute_url())
        self.assertEqual(neologism.form, "currus electricus")
        self.assertEqual(neologism.evidences.count(), 2)
        response = self.client.post(url, data | {"justification": ""})
        self.assertContains(response, "Ce champ est obligatoire")

    def test_equivalents_and_evidence_pages(self):
        self.client.force_login(self.other)
        add = reverse("phraseology:neologism_equivalent_add", args=[self.neologism.pk])
        self.client.post(add, {"language": "en", "expression": "bike"})
        self.assertEqual(self.neologism.equivalents.active().count(), 2)
        bicycle = self.neologism.equivalents.get(expression="bike")
        withdraw = reverse("phraseology:neologism_equivalent_withdraw", args=[bicycle.pk])
        response = self.client.post(withdraw, follow=True)
        self.assertContains(response, "Le retrait est enregistré")
        self.assertNotContains(response, "bike")
        url = reverse("phraseology:neologism_evidence_add", args=[self.neologism.pk])
        response = self.client.get(url, {"term1": "capiunt"})
        self.assertContains(response, f'value="{self.more_words[1].pk}" form="unit-form"')
        self.assertContains(response, "cochez celles qui justifient votre choix")
        management = {
            "references-TOTAL_FORMS": "2",
            "references-INITIAL_FORMS": "0",
            "references-MIN_NUM_FORMS": "0",
            "references-MAX_NUM_FORMS": "5",
        }
        self.client.post(url, management | {"attestation": [str(self.more_words[1].pk)]})
        self.assertEqual(self.neologism.evidences.count(), 3)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
