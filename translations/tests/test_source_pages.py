from django.urls import reverse

from translations.models import SourceChange, SourceProposal
from translations.services import change_source_text

from .factories import make_published_version
from .test_versions import TranslationTestCase


class SourceSentencePagesTests(TranslationTestCase):
    def url(self, name, *args):
        return reverse(f"translations:{name}", args=[self.source.pk, *args])

    def texts(self):
        return list(self.source.segments.current().values_list("text", flat=True))

    def test_the_sentences_page_offers_changes_to_whoever_may(self):
        page = self.client.get(self.url("source_sentences"))
        self.assertContains(page, "Nous restons à la maison.")
        self.assertNotContains(page, self.url("source_sentence_edit", 1))
        for user in (self.author, self.reviewer):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                page = self.client.get(self.url("source_sentences"))
                self.assertContains(page, self.url("source_sentence_edit", 1))
                self.assertContains(page, self.url("source_sentence_merge", 2))
                self.assertNotContains(page, self.url("source_sentence_merge", 3))
        project = self.client.get(self.project.get_absolute_url())
        self.assertContains(project, "Modifier le texte à traduire")
        edit_page = self.client.get(reverse("translations:source_edit", args=[self.source.pk]))
        self.assertNotContains(edit_page, "ne change pas")

        # Any other account finds the same actions, but its changes form a proposal.
        self.client.force_login(self.other)
        page = self.client.get(self.url("source_sentences"))
        self.assertContains(page, self.url("source_sentence_edit", 1))
        response = self.client.post(self.url("source_sentence_merge", 1), {"state": 0})
        self.assertRedirects(response, self.url("source_sentences") + "#phrase-1")
        self.assertFalse(SourceChange.objects.exists())
        self.assertTrue(SourceProposal.objects.filter(author=self.other).exists())
        self.client.logout()
        response = self.client.post(self.url("source_sentence_merge", 1), {"state": 0})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SourceChange.objects.exists())

    def test_a_sentence_is_edited_split_and_merged(self):
        self.client.force_login(self.author)
        response = self.client.post(
            self.url("source_sentence_edit", 2), {"state": 0, "text": " Nous restons chez nous. "}
        )
        self.assertRedirects(response, self.url("source_sentences") + "#phrase-2")
        self.assertEqual(self.texts()[1], "Nous restons chez nous.")
        response = self.client.post(
            self.url("source_sentence_split", 2), {"state": 1, "parts": "Nous restons\nchez nous."}
        )
        self.assertRedirects(response, self.url("source_sentences") + "#phrase-2")
        self.assertEqual(
            self.texts(), ["Il pleut.", "Nous restons", "chez nous.", "Demain, nous partirons."]
        )
        response = self.client.post(self.url("source_sentence_merge", 2), {"state": 2}, follow=True)
        self.assertContains(response, "Le texte est modifié.")
        self.assertEqual(self.texts()[1], "Nous restons chez nous.")
        self.assertContains(response, "Changement 3 : fusion")

    def test_a_change_made_on_an_outdated_page_is_refused(self):
        self.client.force_login(self.author)
        change_source_text(self.source, {"kind": "merge", "index": 1}, self.author)
        response = self.client.post(
            self.url("source_sentence_edit", 1), {"state": 0, "text": "Il pleut fort."}
        )
        self.assertContains(response, "Le texte a changé pendant que vous le modifiiez")
        self.assertEqual(response.context["form"]["state"].value(), 1)
        self.assertEqual(self.texts()[0], "Il pleut.")
        response = self.client.post(
            self.url("source_sentence_split", 1), {"state": 1, "parts": "Il\npleure."}
        )
        self.assertContains(response, "Une scission ne change aucun mot")

    def test_sentences_are_added_after_checking_the_split(self):
        self.client.force_login(self.author)
        url = self.url("source_sentence_insert") + "?apres=1"
        self.assertContains(self.client.get(url), "Ajouter des phrases après la phrase 1")
        response = self.client.post(
            url, {"state": 0, "text": "Le vent souffle. Les arbres plient."}
        )
        self.assertEqual(
            response.context["form"]["text"].value(), "Le vent souffle.\nLes arbres plient."
        )
        self.assertFalse(SourceChange.objects.exists())
        data = {
            "state": 0,
            "segmented": "1",
            "text": "Le vent souffle.\nLes arbres plient.",
            "new_paragraph": "on",
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, self.url("source_sentences") + "#phrase-2")
        self.assertEqual(self.texts()[:3], ["Il pleut.", "Le vent souffle.", "Les arbres plient."])
        self.assertTrue(self.source.segments.current().get(order=2).starts_paragraph)
        for after, heading in ((0, "au début"), (5, "à la fin")):
            with self.subTest(after=after):
                page = self.client.get(self.url("source_sentence_insert") + f"?apres={after}")
                self.assertContains(page, f"Ajouter des phrases {heading}")
        page = self.client.get(self.url("source_sentence_insert") + "?apres=9")
        self.assertEqual(page.status_code, 404)


class SourceChangedInTheEditorTests(TranslationTestCase):
    def test_the_author_sees_the_sentences_touched_since_the_last_step(self):
        version = make_published_version(self.author, self.project)
        change_source_text(self.source, {"kind": "merge", "index": 0}, self.author)
        insert = {"kind": "insert", "before": 2, "sentences": [{"text": "À bientôt."}]}
        change_source_text(self.source, insert, self.author)

        self.client.force_login(self.author)
        for name in ("version", "version_edit"):
            with self.subTest(page=name):
                page = self.client.get(reverse(f"translations:{name}", args=[version.pk]))
                self.assertContains(page, "Le texte source a changé depuis l’étape 1")
                rows = page.context["rows"]
                self.assertEqual([row["source_changed"] for row in rows], [True, False, True])
                self.assertEqual(
                    [old.text for old in rows[0]["previous_sources"]],
                    ["Il pleut.", "Nous restons à la maison."],
                )
                self.assertContains(page, "Texte source changé depuis la dernière étape")
                self.assertContains(page, "Phrase ajoutée au texte source depuis la dernière étape")

        self.client.logout()
        page = self.client.get(version.get_absolute_url())
        self.assertNotContains(page, "Texte source changé")
        compare = self.client.get(reverse("translations:project_compare", args=[self.project.pk]))
        older = [cell["older"] for row in compare.context["rows"] for cell in row["cells"]]
        self.assertEqual(older, [True, False, True])
        self.assertContains(compare, "d’après un texte source antérieur")
