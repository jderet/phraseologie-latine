from django.urls import reverse

from phraseology.models import Attestation, Equivalent, Unit
from phraseology.services import add_attestations, propose_unit, save_part, update_unit

from .factories import evidence, set_status
from .test_frequency import AnalysedCorpusTestCase


class WordPanelTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        update_unit(self.unit, self.author)
        propose_unit(self.unit, self.author)
        self.attestation = self.unit.attestations.get()
        sense = self.unit.senses.get()
        save_part(Equivalent(sense=sense, language="fr", expression="se décider"), self.author)
        add_attestations(self.unit, [evidence(*self.more_words[:2])], self.author)
        self.url = reverse("phraseology:reading_word", args=[self.words[0].pk])
        self.reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])

    def test_the_units_of_a_word_and_its_analysis(self):
        response = self.client.get(self.url, {"fragment": "1"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, self.unit.get_absolute_url())
        self.assertContains(response, "prendre une décision")
        self.assertContains(response, "se décider")
        self.assertContains(
            response, "4 occurrences du schéma repérées automatiquement, dont 3 dans le noyau"
        )
        self.assertContains(response, "Consilia")
        self.assertContains(response, "Proposée")
        self.assertContains(response, "nom commun")
        self.assertContains(response, "objet")
        self.assertContains(response, "dépend de")
        self.assertContains(response, "LatinCy test 1.0")
        self.assertNotContains(response, 'name="decision"')

    def test_without_script_the_panel_is_a_page(self):
        response = self.client.get(self.url)
        self.assertContains(response, "<html")
        self.assertContains(response, f'href="{self.reading}?aller=1.1"')

    def test_a_draft_stays_hidden(self):
        set_status(self.unit, Unit.Status.DRAFT)
        response = self.client.get(self.url, {"fragment": "1"})
        self.assertContains(response, "Ce mot n’appartient à aucune unité soulignée.")

    def test_a_reviewer_decides_in_the_panel_and_goes_back_to_the_reading(self):
        self.client.force_login(self.reviewer)
        back = f"{self.reading}?fiche={self.unit.pk}#p-1.1"
        response = self.client.get(self.url, {"fragment": "1", "retour": back})
        self.assertContains(response, 'name="decision" value="valider"')
        self.assertContains(response, f'name="next" value="{back}"')
        review = reverse("phraseology:attestation_review", args=[self.attestation.pk])
        response = self.client.post(review, {"decision": "valider", "next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.attestation.refresh_from_db()
        self.assertEqual(self.attestation.status, Attestation.Status.VALIDATED)
        response = self.client.post(review, {"decision": "rejeter", "next": "https://example.com/"})
        expected = self.attestation.get_absolute_url()
        self.assertRedirects(response, expected, fetch_redirect_response=False)
