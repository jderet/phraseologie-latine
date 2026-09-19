from django.urls import reverse

from translations.services import set_sentence_status

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class EditorFilterTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version, ("Pluit.", "Domi manemus."))
        set_sentence_status(self.version, self.second, "reviewed", self.author)
        self.client.force_login(self.author)
        self.url = reverse("translations:version_edit", args=[self.version.pk])

    def shown(self, **params):
        response = self.client.get(self.url, params)
        return [row["number"] for row in response.context["shown_rows"]]

    def test_filters(self):
        self.assertEqual(self.shown(), [1, 2, 3])
        self.assertEqual(self.shown(filtre="a-traduire"), [3])
        self.assertEqual(self.shown(filtre="brouillons"), [1])
        self.assertEqual(self.shown(filtre="non-relues"), [1])

    def test_search_ignores_accents_and_case(self):
        self.assertEqual(self.shown(q="MAISON"), [2])
        self.assertEqual(self.shown(q="pluit"), [1])
        self.assertEqual(self.shown(q="demain"), [3])

    def test_an_empty_filter_says_so(self):
        response = self.client.get(self.url, {"q": "introuvable"})
        self.assertContains(response, "Aucune phrase ne correspond à ce filtre.")

    def test_saving_a_filtered_page_keeps_the_other_sentences(self):
        response = self.client.post(
            self.url + "?filtre=a-traduire", {f"s{self.third.pk}": "Cras proficiscemur."}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.shown(filtre="a-traduire"), [])
        self.assertEqual(self.shown(filtre="brouillons"), [1, 3])

    def test_shortcuts_are_listed(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Raccourcis clavier")
