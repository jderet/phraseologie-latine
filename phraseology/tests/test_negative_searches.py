from django.contrib.messages import get_messages
from django.http import QueryDict
from django.urls import reverse

from corpus.forms import bound_search_form, search_query
from corpus.search import corpus_version
from moderation.models import Revision
from phraseology.models import NegativeSearch

from .factories import make_layer
from .test_units import PhraseologyTestCase

NOTHING = "term1=sumpsit&term2=consilium&scope=all"


class SearchQueryTests(PhraseologyTestCase):
    def test_a_query_keeps_the_search_parameters_in_order(self):
        data = QueryDict("page=3&scope=all&term2=consilium&term1=sumpsit&other=x")
        self.assertEqual(search_query(data), NOTHING)
        data = QueryDict("term5=bene&distance=8&term4=publica&term1=de&mode5=lemma")
        self.assertEqual(
            search_query(data), "term1=de&term4=publica&term5=bene&mode5=lemma&distance=8"
        )

    def test_a_search_described_in_words(self):
        make_layer()
        form = bound_search_form(QueryDict("term1=consilium&mode1=lemma&term2=cap*&ordered=on"))
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.description,
            "consilium (lemme) + cap* (forme), à 5 mots au plus, dans cet ordre, noyau",
        )
        form = bound_search_form(QueryDict("term1=de&term2=re&term4=publica&term5=bene"))
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.description,
            "de (forme) + re (forme) + publica (forme) + bene (forme), à 5 mots au plus, noyau",
        )
        form = bound_search_form(QueryDict("term1=abiret&scope=all&date_from=-50"))
        self.assertTrue(form.is_valid())
        self.assertEqual(form.description, "abiret (forme), tout le corpus, avec filtres")


class NegativeSearchTests(PhraseologyTestCase):
    url = reverse("phraseology:negative_search_create")

    def record(self, query=NOTHING, expression="consilium sumere"):
        return self.client.post(self.url, {"query": query, "expression": expression, "note": ""})

    def test_a_search_that_finds_nothing_is_recorded_with_the_corpus_version(self):
        self.client.force_login(self.author)
        response = self.record(f"{NOTHING}&page=2")
        search = NegativeSearch.objects.get()
        self.assertRedirects(response, search.get_absolute_url())
        self.assertEqual(search.query, NOTHING)
        self.assertEqual(search.corpus_version, corpus_version().label)
        self.assertEqual(search.created_by, self.author)
        self.assertEqual(Revision.objects.for_object(search).count(), 1)
        page = self.client.get(search.get_absolute_url())
        self.assertContains(page, f"Introuvable dans le corpus (version {search.corpus_version}).")
        self.assertContains(page, "sumpsit (forme) + consilium (forme), à 5 mots au plus")
        self.assertContains(page, "Le corpus n’a pas changé depuis l’enregistrement.")
        self.assertContains(page, search.search_url.replace("&", "&amp;"))

    def test_a_search_that_finds_something_or_is_not_valid_is_refused(self):
        self.client.force_login(self.author)
        response = self.record("term1=cepit")
        self.assertRedirects(
            response, f"{reverse('corpus:search')}?term1=cepit", fetch_redirect_response=False
        )
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "Cette recherche trouve des occurrences : elle n’est pas infructueuse.", messages
        )
        self.record("term1=a*")
        self.record(NOTHING, expression="")
        self.assertFalse(NegativeSearch.objects.exists())

    def test_only_signed_in_accounts_record(self):
        response = self.record()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(NegativeSearch.objects.exists())

    def test_the_search_is_run_again_on_a_changed_corpus(self):
        self.client.force_login(self.author)
        self.record()
        search = NegativeSearch.objects.get()
        NegativeSearch.objects.update(corpus_version="Perseus 0000000")
        page = self.client.get(search.get_absolute_url())
        self.assertContains(page, "la recherche reste infructueuse")
        NegativeSearch.objects.update(query="term1=cepit")
        page = self.client.get(search.get_absolute_url())
        self.assertContains(page, "Le corpus a changé depuis : 1 occurrence dans la version")
        NegativeSearch.objects.update(query="term1=a*")
        self.assertContains(
            self.client.get(search.get_absolute_url()), "cette recherche n’est plus valable"
        )

    def test_search_results_offer_to_record_an_absence(self):
        search_url = reverse("corpus:search")
        self.client.force_login(self.author)
        page = self.client.get(f"{search_url}?{NOTHING}")
        self.assertContains(page, "Introuvable dans le corpus interrogé")
        self.assertContains(page, f'name="query" value="{NOTHING.replace("&", "&amp;")}"')
        self.assertContains(page, 'value="sumpsit consilium"')
        self.assertContains(page, "Enregistrer cette recherche infructueuse")
        self.assertNotContains(
            self.client.get(search_url, {"term1": "cepit"}), "Enregistrer cette recherche"
        )
        panel = self.client.get(reverse("corpus:search_fragment"), {"term1": "sumpsit"})
        self.assertNotContains(panel, "Enregistrer cette recherche")
        self.client.logout()
        page = self.client.get(f"{search_url}?{NOTHING}")
        self.assertNotContains(page, "Enregistrer cette recherche")
        self.assertContains(page, reverse("phraseology:negative_search_list"))

    def test_the_list_of_recorded_searches(self):
        self.client.force_login(self.author)
        self.record()
        page = self.client.get(reverse("phraseology:negative_search_list"))
        self.assertContains(page, "consilium sumere")
        self.assertContains(page, "sumpsit (forme) + consilium (forme)")
        self.assertNotContains(page, "ancienne version")
