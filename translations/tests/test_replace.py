from django.test import SimpleTestCase
from django.urls import reverse

from translations.models import TranslatedSegment
from translations.replace import build_pattern

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class PatternTests(SimpleTestCase):
    def test_macrons_are_ignored_by_default(self):
        pattern = build_pattern("domi")
        self.assertTrue(pattern.search("Dōmī manēmus"))

    def test_whole_word_and_case(self):
        self.assertIsNone(build_pattern("man", whole_word=True).search("manemus"))
        self.assertIsNone(build_pattern("pluit", match_case=True).search("Pluit"))
        self.assertTrue(build_pattern("pluit").search("Pluit"))

    def test_special_characters_are_plain_text(self):
        self.assertTrue(build_pattern("(a.b)").search("x (a.b) y"))
        self.assertIsNone(build_pattern("(a.b)").search("x (acb) y"))

    def test_nothing_to_find(self):
        self.assertIsNone(build_pattern("  "))


class ReplacePageTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version, ("Pluit.", "Domi manemus.", "Cras domi erimus."))
        self.client.force_login(self.author)
        self.url = reverse("translations:find_replace", args=[self.version.pk])

    def text(self, segment):
        return TranslatedSegment.objects.get(version=self.version, segment=segment).text

    def test_preview_then_replace_the_chosen_sentences(self):
        params = {"find": "domi", "replace": "domī", "ignore_macrons": "on", "whole_word": "on"}
        response = self.client.get(self.url, params)
        self.assertEqual(len(response.context["changes"]), 2)
        response = self.client.post(self.url, {**params, "phrase": [self.second.pk]})
        self.assertRedirects(response, reverse("translations:version_edit", args=[self.version.pk]))
        self.assertEqual(self.text(self.second), "Domī manemus.")
        self.assertEqual(self.text(self.third), "Cras domi erimus.")

    def test_replacement_is_not_a_pattern(self):
        self.client.post(
            self.url, {"find": "Pluit", "replace": r"\1 $&", "phrase": [self.first.pk]}
        )
        self.assertEqual(self.text(self.first), r"\1 $&.")

    def test_writers_only(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
