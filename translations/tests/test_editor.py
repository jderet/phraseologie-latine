from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from translations.models import TranslatedSegment

from .factories import make_source_text, make_version
from .test_versions import TranslationTestCase


class EditorPageTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        self.url = reverse("translations:version_edit", args=[self.version.pk])

    def test_three_columns_with_corpus_search_and_macrons(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        save_url = reverse("translations:translation_save", args=[self.version.pk, self.first.pk])
        self.assertContains(response, 'class="page-wide"')
        self.assertContains(response, 'class="editor-panel"')
        self.assertContains(response, f'data-save-url="{save_url}"')
        self.assertContains(response, f'data-fragment-url="{reverse("corpus:search_fragment")}"')
        self.assertContains(response, 'name="term5"')
        self.assertContains(response, 'data-insert="ā"')
        self.assertContains(response, 'data-insert="Ȳ"')
        self.assertContains(response, "js/editor.js")


class SentenceSaveTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        self.url = reverse("translations:translation_save", args=[self.version.pk, self.first.pk])

    def test_a_sentence_is_saved_and_the_answer_is_json(self):
        self.client.force_login(self.author)
        response = self.client.post(self.url, {"text": "  Pluīt   hodie. "})
        self.assertEqual(
            response.json(), {"text": "Pluīt hodie.", "changed": True, "status": "draft"}
        )
        response = self.client.post(self.url, {"text": "Pluīt hodie."})
        self.assertEqual(response.json()["changed"], False)
        self.assertEqual(TranslatedSegment.objects.get().text, "Pluīt hodie.")

    def test_errors_are_returned(self):
        newcomer = make_user(email="new@example.org", role=CONTRIBUTOR)
        version = make_version(newcomer, self.project)
        self.client.force_login(newcomer)
        url = reverse("translations:translation_save", args=[version.pk, self.first.pk])
        response = self.client.post(url, {"text": "vide www.example.org"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Les liens ne sont pas autorisés", response.json()["errors"][0])
        self.assertFalse(TranslatedSegment.objects.exists())

    def test_only_the_author_saves_with_a_post(self):
        self.assertEqual(self.client.post(self.url, {"text": "Pluit."}).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url, {"text": "Pluit."}).status_code, 404)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(TranslatedSegment.objects.exists())

    def test_the_sentence_must_belong_to_the_text(self):
        other_source = make_source_text(self.author, title="Autre texte")
        url = reverse(
            "translations:translation_save",
            args=[self.version.pk, other_source.segments.first().pk],
        )
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(url, {"text": "Pluit."}).status_code, 404)
