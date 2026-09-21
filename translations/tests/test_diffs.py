from django.test import SimpleTestCase
from django.urls import reverse

from translations.diffs import ADDED, REMOVED, SAME, Chunk, word_diff
from translations.services import create_step, publish_version, save_translation

from .factories import make_project, make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class WordDiffTests(SimpleTestCase):
    def test_changed_words(self):
        self.assertEqual(
            word_diff("Domi manemus.", "Domi maneamus."),
            [
                Chunk(SAME, "Domi "),
                Chunk(REMOVED, "manemus"),
                Chunk(ADDED, "maneamus"),
                Chunk(SAME, "."),
            ],
        )

    def test_added_and_removed_words(self):
        self.assertEqual(
            word_diff("Venīsne ad nōs?", "Venīsne ad nōs crās?"),
            [Chunk(SAME, "Venīsne ad nōs"), Chunk(ADDED, " crās"), Chunk(SAME, "?")],
        )
        self.assertEqual(word_diff("Pluit.", ""), [Chunk(REMOVED, "Pluit.")])
        self.assertEqual(word_diff("", "Pluit."), [Chunk(ADDED, "Pluit.")])
        self.assertEqual(word_diff("Pluit.", "Pluit."), [Chunk(SAME, "Pluit.")])


class StepCompareTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        save_translation(self.version, self.second, "Domi maneamus.", self.author)
        create_step(self.version, self.author, "Subjonctif")
        save_translation(self.version, self.third, "Cras abibimus.", self.author)
        self.url = reverse("translations:step_compare", args=[self.version.pk])

    def test_the_changes_of_a_step_word_by_word(self):
        response = self.client.get(self.url)
        self.assertEqual(
            (response.context["base"].number, response.context["target"].number), (1, 2)
        )
        [row] = response.context["rows"]
        self.assertEqual(row["segment"], self.second)
        self.assertContains(response, "<del>manemus</del><ins>maneamus</ins>", html=True)
        response = self.client.get(self.url, {"de": "", "a": "1"})
        self.assertEqual(len(response.context["rows"]), 3)
        self.assertIsNone(response.context["base"])

    def test_the_working_text_is_compared_for_its_author_only(self):
        response = self.client.get(self.url, {"a": "travail"})
        self.assertEqual(response.context["target"].number, 2)
        self.assertNotContains(response, "abibimus")
        self.client.force_login(self.author)
        response = self.client.get(self.url, {"a": "travail"})
        self.assertIsNone(response.context["target"])
        self.assertEqual(response.context["base"].number, 2)
        self.assertContains(response, "<ins>abibimus</ins>", html=True)

    def test_hidden_draft_steps_are_not_offered(self):
        version = make_version(self.other, make_project(self.other, self.source, title="Autre"))
        translate(version, ("Pluvia.",))
        create_step(version, self.other, "Brouillon")
        publish_version(version, self.other)
        url = reverse("translations:step_compare", args=[version.pk])
        response = self.client.get(url, {"de": "1", "a": "2"})
        self.assertEqual([step.number for step in response.context["steps"]], [2])
        self.assertIsNone(response.context["base"])

    def test_each_sentence_tells_its_step_and_who_wrote_it(self):
        translated = self.version.segments.get(segment=self.third)
        translated.written_by = self.other
        translated.save()
        create_step(self.version, self.author, "Proposition de Quintus")
        response = self.client.get(reverse("translations:step", args=[self.version.pk, 3]))
        origins = [row["origin"] for row in response.context["rows"]]
        self.assertEqual([origin["step"].number for origin in origins], [1, 2, 3])
        self.assertEqual([origin["written_by"] for origin in origins], [None, None, self.other])
        self.assertContains(response, "écrite par Quintus")
