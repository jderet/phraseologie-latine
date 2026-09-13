from django.test import TestCase
from django.urls import reverse

from corpus.models import Author
from corpus.search import build_hits, corpus_version, parse_term, search_tokens

from .utils import PerseusSourceMixin

CORE = {"core_only": True}


class SearchTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def forms(self, *terms, **options):
        options.setdefault("filters", CORE)
        hits = search_tokens([parse_term(term) for term in terms], **options)
        return [(hit.form, hit.passage.citation) for hit in hits]

    def test_form_search_ignores_case_and_macrons(self):
        self.assertEqual(self.forms("ATHENIS"), [("Athenis", "Cic. Off. 1, 1")])
        self.assertEqual(self.forms("cōnsilium"), [("consilium", "Cic. Off. 1, 2")])

    def test_prefixes_and_variants(self):
        self.assertEqual(self.forms("consil*"), [("consilium", "Cic. Off. 1, 2")])
        self.assertEqual(self.forms("cap* | cep*"), [("cepit", "Cic. Off. 1, 2")])

    def test_terms_within_a_distance(self):
        self.assertEqual(len(self.forms("consilium", "cap* | cep*", distance=1)), 1)
        self.assertEqual(self.forms("consilium", "Tullius", distance=5), [])
        self.assertEqual(len(self.forms("consilium", "Tullius", distance=10)), 1)

    def test_order_can_be_imposed(self):
        self.assertEqual(len(self.forms("cepit", "consilium")), 1)
        self.assertEqual(self.forms("cepit", "consilium", ordered=True), [])

    def test_core_and_author_filters(self):
        self.assertEqual(self.forms("Lucina"), [])
        self.assertEqual(len(self.forms("Lucina", filters={"core_only": False})), 1)
        livy = Author.objects.filter(cts_id="phi0914")
        self.assertEqual(len(self.forms("iam")), 2)
        self.assertEqual(self.forms("iam", filters={"authors": livy}), [("Iam", "Liv. 1, 1, 1")])

    def test_genre_and_date_filters(self):
        tragedy = {"genres": ["tragedy"]}
        self.assertEqual(len(self.forms("Lucina", filters=tragedy)), 1)
        self.assertEqual(len(self.forms("iam", filters={**CORE, "date_from": 1})), 1)

    def test_context_and_highlighted_words(self):
        terms = [parse_term("consilium"), parse_term("cep*")]
        hits = build_hits(search_tokens(terms, filters=CORE), terms)
        self.assertEqual(len(hits), 1)
        words = [word.form for word in hits[0].words]
        self.assertIn("Cratippum", words)
        self.assertIn("Tullius", words)
        highlighted = [w.form for w in hits[0].words if w.pk in hits[0].highlighted]
        self.assertEqual(highlighted, ["consilium", "cepit"])
        self.assertIn("/corpus/phi0474.phi055/1.2/?mots=", hits[0].url)

    def test_corpus_version(self):
        version = corpus_version()
        self.assertEqual(version.label, "Perseus aaaaaaa")
        self.assertEqual(version.edition_count, 4)


class SearchPageTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()
        self.url = reverse("corpus:search")

    def test_empty_form(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Recherche dans le corpus")
        self.assertNotContains(response, "Corpus interrogé")

    def test_results_with_context_distribution_and_version(self):
        response = self.client.get(self.url, {"term1": "consilium", "term2": "cap* | cep*"})
        self.assertContains(response, "1 occurrence")
        self.assertContains(response, "Cic. Off. 1, 2")
        self.assertContains(response, "<mark", count=2)
        self.assertContains(response, "Cicéron")
        self.assertContains(response, "Perseus aaaaaaa")

    def test_absence_names_the_corpus_version(self):
        response = self.client.get(self.url, {"term1": "consilium", "term2": "inire"})
        self.assertContains(
            response, "Introuvable dans le corpus interrogé (version Perseus aaaaaaa)"
        )
        self.assertContains(response, "noyau seulement")
        self.assertNotContains(response, "non attesté")

    def test_whole_corpus_scope(self):
        response = self.client.get(self.url, {"term1": "Lucina", "scope": "all"})
        self.assertContains(response, "Sen. Med. 2")

    def test_invalid_terms(self):
        response = self.client.get(self.url, {"term1": "c*"})
        self.assertContains(response, "au moins deux lettres")
        response = self.client.get(self.url, {"term1": "consilium capere"})
        self.assertContains(response, "Un seul mot par case")
