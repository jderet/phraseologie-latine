from django.urls import reverse

from translations.services import save_translation

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class StatsTests(TranslationTestCase):
    def test_writers_see_the_working_text_and_the_pace(self):
        version = make_version(self.author, self.project)
        translate(version, ("Pluit.", "Domi manemus."))
        self.client.force_login(self.author)
        response = self.client.get(reverse("translations:version_stats", args=[version.pk]))
        stats = response.context["stats"]
        self.assertEqual(stats["translated"], 2)
        self.assertEqual(stats["latin_words"], 3)
        self.assertEqual(len(stats["pace"]), 30)
        self.assertEqual(stats["pace"][-1]["count"], 2)
        self.assertContains(response, "Qui a écrit quoi")

    def test_the_public_sees_the_public_step_without_the_pace(self):
        version = make_published_version(self.author, self.project)
        save_translation(version, self.first, "Imber cadit hodie valde.", self.author)
        response = self.client.get(reverse("translations:version_stats", args=[version.pk]))
        stats = response.context["stats"]
        self.assertEqual(stats["latin_words"], 5)
        self.assertNotIn("pace", stats)

    def test_a_draft_stays_private(self):
        version = make_version(self.author, self.project)
        response = self.client.get(reverse("translations:version_stats", args=[version.pk]))
        self.assertEqual(response.status_code, 404)
