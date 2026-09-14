from django.urls import reverse

from accounts.services import anonymize_user
from notebook.models import Highlight, PassageList, PrivateNote
from notebook.services import add_highlight, add_private_note, add_to_list, notebook_marks
from phraseology.tests.test_frequency import AnalysedCorpusTestCase


def ids(words):
    return ",".join(str(word.pk) for word in words)


class NotebookServiceTests(AnalysedCorpusTestCase):
    def test_what_a_reader_keeps_shows_to_that_reader_only(self):
        highlight = add_highlight(self.other, ids(self.words[:2]), "green")
        note = add_private_note(self.other, ids(self.words[2:4]), "À relire.")
        add_to_list(self.other, self.passage, "Exemples")
        add_to_list(self.other, self.second_passage, " Exemples ")
        self.assertEqual(PassageList.objects.get().entries.count(), 2)
        token_ids = {word.pk for word in self.words}
        marks = notebook_marks(self.other, [self.passage], token_ids)
        self.assertEqual(
            sorted(mark.key for mark in marks), sorted([f"h_{highlight.pk}", f"n_{note.pk}"])
        )
        self.assertEqual(sorted(mark.css for mark in marks), ["hl hl-green", "pn"])
        self.assertEqual(notebook_marks(self.author, [self.passage], token_ids), [])

    def test_deleting_the_account_deletes_the_notebook(self):
        add_highlight(self.other, ids(self.words[:2]))
        add_private_note(self.other, ids(self.words[:2]), "Note.")
        add_to_list(self.other, self.passage, "Liste")
        anonymize_user(self.other)
        self.assertFalse(Highlight.objects.exists())
        self.assertFalse(PrivateNote.objects.exists())
        self.assertFalse(PassageList.objects.exists())


class NotebookViewTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])

    def test_the_notebook_is_private(self):
        add_highlight(self.other, ids(self.words[:2]))
        url = reverse("notebook:notebook")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Aucun surlignage.")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(url), "Cic. Off. 1, 1")

    def test_the_panels_of_the_reading_add_to_the_notebook(self):
        self.client.force_login(self.other)
        words = ids(self.words[:2])
        create = reverse("notebook:highlight_create")
        self.assertContains(self.client.get(create, {"mots": words, "fragment": "1"}), "Surligner")
        response = self.client.post(create, {"words": words, "color": "blue", "next": self.reading})
        self.assertRedirects(response, self.reading, fetch_redirect_response=False)
        highlight = Highlight.objects.get()
        self.assertEqual(highlight.color, "blue")
        note = {"words": ids(self.words[2:4]), "text": "Voir Off. 1, 23.", "next": self.reading}
        self.client.post(reverse("notebook:note_create"), note)
        self.client.post(
            reverse("notebook:list_add"),
            {"passage": self.passage.pk, "name": "À relire", "next": self.reading},
        )
        self.assertEqual(PassageList.objects.get().name, "À relire")
        page = self.client.get(self.reading)
        self.assertContains(page, 'class="hl hl-blue"')
        self.assertContains(page, 'class="pn"')
        self.client.force_login(self.author)
        self.assertNotContains(self.client.get(self.reading), 'class="hl hl-blue"')
        delete = reverse("notebook:highlight_delete", args=[highlight.pk])
        self.assertEqual(self.client.post(delete).status_code, 404)
