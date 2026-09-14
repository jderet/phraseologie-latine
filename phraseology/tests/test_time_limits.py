from unittest import mock

from django.urls import reverse

from corpus.tests.test_timeouts import canceled_query
from phraseology.models import NegativeSearch

from .test_frequency import AnalysedCorpusTestCase
from .test_negative_searches import NOTHING
from .test_units import PhraseologyTestCase


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
