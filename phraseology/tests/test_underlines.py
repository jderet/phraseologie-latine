from django.urls import reverse

from justifications.models import Justification
from justifications.services import create_justification
from phraseology.services import propose_unit, update_unit
from translations.models import TranslatedSegment
from translations.tests.factories import make_project, make_published_version

from .factories import evidence
from .test_frequency import AnalysedCorpusTestCase


class CorpusUnderlineTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        self.attestation = self.unit.attestations.get()

    def test_the_page_of_a_passage(self):
        url = reverse("corpus:passage", args=[self.passage.edition.work.cts_id, "1.1"])
        response = self.client.get(url)
        self.assertContains(
            response,
            f'<span class="u k-none s-proposed t0" data-o="{self.attestation.pk}">Consilium</span>',
            html=True,
        )
        self.assertContains(response, "Phraséologie de ce passage")
        reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])
        self.client.get(reading, {"filtres": "1", "statut": "validated"})
        self.assertNotContains(self.client.get(url), 'class="u ')

    def test_the_results_of_a_search(self):
        response = self.client.get(reverse("corpus:search"), {"term1": "consilium"})
        self.assertContains(
            response, f'class="u k-none s-proposed t0" data-o="{self.attestation.pk}"'
        )


class TranslationUnderlineTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        update_unit(self.unit, self.author)
        propose_unit(self.unit, self.author)
        self.project = make_project(self.author)
        texts = ("Consilium cepit.", "Domi manemus.", "Cras proficiscemur.")
        self.version = make_published_version(self.author, self.project, texts=texts)

    def test_known_units_are_spotted_in_the_published_version(self):
        response = self.client.get(self.version.get_absolute_url())
        self.assertContains(
            response,
            '<span class="u k-none s-spotted t0" title="consilium capere">Consilium</span>',
        )
        self.assertContains(response, "Unités repérées")
        self.assertContains(response, "Domi manemus.")

    def test_the_words_justified_by_an_entry(self):
        segment = TranslatedSegment.objects.get(version=self.version, segment__order=1)
        justification = Justification(
            translated_segment=segment, latin_excerpt="Consilium cepit", strength=1
        )
        create_justification(
            justification, self.author, [evidence(*self.words[:2])], units=[self.unit]
        )
        response = self.client.get(self.version.get_absolute_url())
        self.assertContains(response, 's-justified t1" title="consilium capere">')

    def test_the_comparison_of_versions(self):
        response = self.client.get(reverse("translations:project_compare", args=[self.project.pk]))
        self.assertContains(response, 's-spotted t0" title="consilium capere">Consilium</span>')
