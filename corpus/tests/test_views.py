from django.test import TestCase
from django.urls import reverse

from corpus.models import Token

from .utils import PerseusSourceMixin


class CorpusPagesTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def test_index_lists_authors_and_works(self):
        response = self.client.get(reverse("corpus:index"))
        self.assertContains(response, "Cicéron")
        self.assertContains(response, reverse("corpus:work", args=["phi0474.phi055"]))
        self.assertContains(response, "106 av. J.-C.")
        self.assertContains(response, "hors noyau")

    def test_work_page_lists_passages(self):
        response = self.client.get(reverse("corpus:work", args=["phi0474.phi055"]))
        self.assertContains(response, "Cic. Off.")
        self.assertContains(response, reverse("corpus:passage", args=["phi0474.phi055", "1.2"]))
        self.assertContains(response, "attestations vérifiées par des personnes")

    def test_passage_page(self):
        response = self.client.get(reverse("corpus:passage", args=["phi0474.phi055", "1.1"]))
        self.assertContains(response, "<h1>Cic. Off. 1, 1</h1>", html=True)
        self.assertContains(response, "Quamquam te, Marce fili,")
        self.assertContains(response, "urn:cts:latinLit:phi0474.phi055.perseus-lat1:1.1")
        self.assertContains(response, reverse("corpus:passage", args=["phi0474.phi055", "1.2"]))
        self.assertNotContains(response, 'rel="prev"')

    def test_words_can_be_highlighted(self):
        word = Token.objects.get(form="Athenis")
        url = reverse("corpus:passage", args=["phi0474.phi055", "1.1"])
        response = self.client.get(f"{url}?mots={word.pk},abc,")
        self.assertContains(response, f'<mark id="mot-{word.pk}">Athenis</mark>', html=True)

    def test_unknown_work_or_reference(self):
        response = self.client.get(reverse("corpus:work", args=["phi0474.phi999"]))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("corpus:passage", args=["phi0474.phi055", "9.9"]))
        self.assertEqual(response.status_code, 404)
