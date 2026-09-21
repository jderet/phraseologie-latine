from django.urls import reverse

from translations.memory import other_versions, score, similar_sentences

from .factories import make_project, make_published_version, make_source_text, make_version
from .test_versions import TranslationTestCase


class MemoryTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)

    def test_score_counts_common_words(self):
        self.assertEqual(score("Il pleut.", "Il pleut."), 100)
        self.assertLess(score("Il pleut beaucoup ce matin.", "Nous partirons."), 60)

    def test_translations_of_other_projects_show_their_public_step(self):
        other_project = make_project(self.other, self.source, title="Autre projet")
        published = make_published_version(self.other, other_project)
        hidden = make_project(self.reviewer, self.source, title="Brouillon")
        draft = make_version(self.reviewer, hidden)
        found = other_versions(self.author, self.version, self.first)
        self.assertEqual([item["version"] for item in found], [published])
        self.assertEqual(found[0]["text"], "Pluit.")
        self.assertNotIn(draft, [item["version"] for item in found])

    def test_similar_sentences_of_another_text(self):
        text = make_source_text(
            self.other, sentences=("Nous restons à la maison ce soir.", "Autre chose.")
        )
        project = make_project(self.other, text)
        make_published_version(self.other, project, texts=("Hodie vesperi domi manemus.",))
        matches = similar_sentences(self.author, self.version, self.second)
        self.assertEqual(len(matches), 1)
        self.assertGreaterEqual(matches[0].score, 60)
        self.assertEqual(matches[0].translations[0]["text"], "Hodie vesperi domi manemus.")

    def test_drafts_of_others_never_feed_the_memory(self):
        text = make_source_text(self.other, sentences=("Nous restons à la maison ce soir.",))
        project = make_project(self.other, text)
        draft = make_version(self.other, project)
        from translations.services import save_translation

        save_translation(draft, text.segments.get(), "Domi manemus.", self.other)
        self.assertEqual(similar_sentences(self.author, self.version, self.second), [])

    def test_panel_for_writers_only(self):
        url = reverse("translations:editor_memory", args=[self.version.pk, self.first.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Dans la traduction principale et les variantes")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_editor_has_a_memory_tab(self):
        self.client.force_login(self.author)
        response = self.client.get(reverse("translations:version_edit", args=[self.version.pk]))
        self.assertContains(response, 'data-tab="memory"')

    def test_the_version_itself_is_not_a_memory(self):
        from translations.services import save_translation

        text = make_source_text(self.author, sentences=("Nous restons à la maison ce soir.",))
        project = make_project(self.author, text)
        version = make_version(self.author, project)
        save_translation(version, text.segments.get(), "Domi manemus.", self.author)
        self.assertEqual(similar_sentences(self.author, version, text.segments.get()), [])
        self.assertEqual(len(similar_sentences(self.author, self.version, self.second)), 1)
