from unittest import mock

from django.urls import reverse

from corpus.tests.test_timeouts import canceled_query
from phraseology.models import NegativeSearch, Unit
from phraseology.services import current_frequency

from .test_frequency import AnalysedCorpusTestCase
from .test_negative_searches import NOTHING
from .test_units import PhraseologyTestCase

SCHEMA = "capio -obj|nsubj:pass-> consilium"
LATER = "trop long à compter maintenant"


class FrequencyTooLongTests(AnalysedCorpusTestCase):
    """A count of occurrences stopped by the time limit never keeps a page waiting."""

    def too_long(self):
        return mock.patch("phraseology.services.count_by_author", side_effect=canceled_query)

    def test_a_unit_is_created_all_the_same(self):
        self.client.force_login(self.other)
        consilia, capiunt = self.more_words[:2]
        data = {
            "reference_form": "consilia capere",
            "schema": SCHEMA,
            "definition": "prendre des décisions",
            "attestation": f"{consilia.pk},{capiunt.pk}",
        }
        with self.too_long():
            response = self.client.post(reverse("phraseology:unit_create"), data, follow=True)
        unit = Unit.objects.get(reference_form="consilia capere")
        self.assertRedirects(response, unit.get_absolute_url())
        self.assertContains(response, LATER)
        self.assertIsNone(current_frequency(unit))

    def test_a_change_is_saved_all_the_same_and_the_count_can_be_asked_again(self):
        self.client.force_login(self.author)
        data = {
            "reference_form": "consilium capere",
            "kind": "verb-noun",
            "schema": SCHEMA,
            "construction": "",
            "register": "standard",
            "tags": "",
        }
        with self.too_long():
            response = self.client.post(
                reverse("phraseology:unit_edit", args=[self.unit.pk]), data, follow=True
            )
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.schema, SCHEMA)
        self.assertContains(response, "Les modifications sont enregistrées.")
        self.assertContains(response, LATER)
        url = reverse("phraseology:unit_frequency", args=[self.unit.pk])
        with self.too_long():
            self.assertContains(self.client.post(url, follow=True), LATER)
        self.assertContains(self.client.post(url, follow=True), "4 occurrences repérées")


class TooBroadSchemaSearchTests(AnalysedCorpusTestCase):
    def test_the_page_asks_to_narrow_a_search_stopped_by_the_time_limit(self):
        with mock.patch("phraseology.views.count_by_author", side_effect=canceled_query):
            page = self.client.get(
                reverse("phraseology:schema_search"),
                {"schema": "capio -obj|nsubj:pass-> consilium"},
            )
        self.assertContains(page, "La recherche a pris trop de temps")
        self.assertNotContains(page, "occurrences repérées automatiquement")


class TooBroadNegativeSearchTests(PhraseologyTestCase):
    def test_a_search_too_long_to_run_again_says_so(self):
        self.client.force_login(self.author)
        self.client.post(
            reverse("phraseology:negative_search_create"),
            {"query": NOTHING, "expression": "consilium sumere", "note": ""},
        )
        search = NegativeSearch.objects.get()
        NegativeSearch.objects.update(corpus_version="Perseus 0000000")
        with mock.patch("corpus.forms.SearchForm.hits", side_effect=canceled_query):
            page = self.client.get(search.get_absolute_url())
        self.assertContains(page, "la recherche a pris trop de temps pour être refaite")
