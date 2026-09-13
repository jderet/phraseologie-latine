import io

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from corpus.search import build_hits, corpus_version, default_layer, parse_term, search_tokens

from .test_analysis import FAKE_ANALYZER
from .utils import PerseusSourceMixin

CORE = {"core_only": True}


class LemmaSearchTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()
        call_command(
            "analyze_corpus", "--analyzer", FAKE_ANALYZER, "--make-default", stdout=io.StringIO()
        )

    def test_a_lemma_finds_its_forms(self):
        hits = search_tokens([parse_term("capio", lemma=True)], filters=CORE)
        self.assertEqual([hit.form for hit in hits], ["cepit"])

    def test_form_and_lemma_together_with_highlighting(self):
        terms = [parse_term("consilium"), parse_term("capio", lemma=True)]
        hits = search_tokens(terms, distance=2, filters=CORE)
        (hit,) = build_hits(hits, terms, distance=2)
        highlighted = sorted(word.form for word in hit.words if word.pk in hit.highlighted)
        self.assertEqual(highlighted, ["cepit", "consilium"])

    def test_the_analysis_layer_is_part_of_the_corpus_version(self):
        self.assertEqual(corpus_version().label, "Perseus aaaaaaa · Fake analyser 1.0")
        self.assertEqual(default_layer().label, "Fake analyser 1.0")

    def test_search_page_in_lemma_mode(self):
        response = self.client.get(
            reverse("corpus:search"),
            {"term1": "consilium", "term2": "capio", "mode2": "lemma"},
        )
        self.assertContains(response, "1 occurrence")
        self.assertContains(response, "Fake analyser 1.0")


class LemmaSearchUnavailableTests(PerseusSourceMixin, TestCase):
    def test_lemma_mode_needs_an_analysed_corpus(self):
        self.import_corpus()
        response = self.client.get(reverse("corpus:search"), {"term1": "capio", "mode1": "lemma"})
        self.assertContains(response, "pas encore disponible")
