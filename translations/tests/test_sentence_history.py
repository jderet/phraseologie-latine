from django.urls import reverse

from translations.models import TranslatedSegment
from translations.sentence_history import sentence_history
from translations.services import create_step, save_translation

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class SentenceHistoryTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version)
        create_step(self.version, self.author, "Premier jet")
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        create_step(self.version, self.author, "Autre tour")
        save_translation(self.version, self.first, "Imber cadit valde.", self.author)

    def test_entries_latest_first_only_where_it_changed(self):
        entries = sentence_history(self.author, self.version, self.first)
        self.assertEqual(
            [entry.text for entry in entries], ["Imber cadit valde.", "Imber cadit.", "Pluit."]
        )
        self.assertIsNone(entries[0].step)
        self.assertEqual([entry.step.number for entry in entries[1:]], [2, 1])
        # The second sentence never changed after the first step.
        self.assertEqual(len(sentence_history(self.author, self.version, self.second)), 1)

    def test_restore_a_step(self):
        self.client.force_login(self.author)
        url = reverse("translations:sentence_restore", args=[self.version.pk, self.first.pk])
        response = self.client.post(url, {"etape": "1"}, headers={"Accept": "application/json"})
        self.assertEqual(response.json(), {"text": "Pluit."})
        self.assertEqual(
            TranslatedSegment.objects.get(version=self.version, segment=self.first).text, "Pluit."
        )

    def test_panel_for_writers_only(self):
        url = reverse("translations:editor_history", args=[self.version.pk, self.first.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Rétablir ce texte")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
