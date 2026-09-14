from django.test import override_settings
from django.urls import reverse

from accounts.limits import ContributionLimitReached
from phraseology.dashboards import annotator_summary
from phraseology.models import ReadingNote
from phraseology.reading_notes import create_reading_note, page_reading_notes, word_reading_notes

from .test_frequency import AnalysedCorpusTestCase


class ReadingNoteTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.passage.edition.work
        self.words = list(self.passage.tokens.order_by("position")[:2])
        self.ids = ",".join(str(token.pk) for token in self.words)

    def test_a_note_is_public_moderated_and_counted_toward_limits(self):
        note = create_reading_note(self.ids, self.other, "  Tournure fréquente.  ")
        self.assertEqual((note.text, note.passage), ("Tournure fréquente.", self.passage))
        (mark,) = page_reading_notes([self.passage], {token.pk for token in self.words})
        self.assertEqual(mark.key, f"l_{note.pk}")
        self.assertEqual(mark.words, [token.pk for token in self.words])
        self.assertEqual(word_reading_notes(self.words[0]), [note])
        note.is_hidden = True
        note.save()
        self.assertEqual(page_reading_notes([self.passage], {self.words[0].pk}), [])
        self.assertEqual(word_reading_notes(self.words[0]), [])
        self.other.is_confirmed = False
        self.other.save()
        with override_settings(NEW_ACCOUNT_DAILY_LIMIT=1):
            with self.assertRaises(ContributionLimitReached):
                create_reading_note(self.ids, self.other, "Une autre.")

    def test_notes_through_the_reading(self):
        create_url = reverse("phraseology:reading_note_create")
        reading = reverse("corpus:reading", args=[self.work.cts_id])
        response = self.client.post(create_url, {"words": self.ids, "text": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ReadingNote.objects.exists())
        self.client.force_login(self.other)
        panel = self.client.get(create_url, {"mots": self.ids, "fragment": "1", "retour": reading})
        self.assertContains(panel, "Publier la note")
        text = "Tournure <b>fréquente</b>."
        response = self.client.post(create_url, {"words": self.ids, "text": text, "next": reading})
        self.assertRedirects(response, reading, fetch_redirect_response=False)
        note = ReadingNote.objects.get()
        response = self.client.get(reading)
        self.assertContains(response, f'data-o="l_{note.pk}"')
        self.assertContains(response, "Tournure &lt;b&gt;fréquente&lt;/b&gt;.")
        hidden = self.client.get(reading, {"filtres": "1", "statut": "validated"})
        self.assertNotContains(hidden, f'data-o="l_{note.pk}"')
        self.assertNotContains(hidden, "Tournure")
        word_url = reverse("phraseology:reading_word", args=[self.words[0].pk])
        self.assertContains(self.client.get(word_url, {"fragment": "1"}), "Tournure &lt;b&gt;")
        self.assertEqual(len(annotator_summary(self.other)["reading_notes"]), 1)
        self.assertContains(self.client.get(reverse("phraseology:annotator")), "Tournure")
