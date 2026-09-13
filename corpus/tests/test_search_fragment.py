from django.test import TestCase
from django.urls import reverse

from .utils import PerseusSourceMixin


class SearchFragmentTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def test_results_without_the_page_around_them(self):
        response = self.client.get(reverse("corpus:search_fragment"), {"term1": "Athenis"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertContains(response, 'target="_blank" rel="noopener"')
        self.assertNotContains(response, 'class="pager"')

    def test_errors_are_shown(self):
        response = self.client.get(reverse("corpus:search_fragment"), {"term1": "a*"})
        self.assertContains(response, "Écrivez au moins deux lettres avant *.")

    def test_the_full_search_page_is_unchanged(self):
        response = self.client.get(reverse("corpus:search"), {"term1": "Athenis"})
        self.assertContains(response, "<html")
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertNotContains(response, 'target="_blank"')
