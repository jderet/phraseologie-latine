from django.urls import reverse

from translations.concordance import SOURCE, highlight, search
from translations.services import create_step, save_translation

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class ConcordanceTests(TranslationTestCase):
    def test_latin_of_the_public_step_only(self):
        version = make_published_version(self.author, self.project)
        # Changed afterwards in the working text, not yet in a step: the public keeps "Pluit."
        save_translation(version, self.first, "Imber cadit.", self.author)
        results, exceeded = search("pluit")
        self.assertFalse(exceeded)
        self.assertEqual([result["latin"] for result in results], ["Pluit."])
        self.assertEqual(search("imber")[0], [])
        create_step(version, self.author, "Autre tour")
        self.assertEqual(search("pluit")[0], [])
        self.assertEqual(len(search("imber")[0]), 1)

    def test_drafts_are_never_searched(self):
        draft = make_version(self.author, self.project)
        translate(draft)
        self.assertEqual(search("pluit")[0], [])

    def test_source_side(self):
        make_published_version(self.author, self.project)
        results, _exceeded = search("maison", SOURCE)
        self.assertEqual([result["latin"] for result in results], ["Domi manemus."])

    def test_too_short(self):
        self.assertEqual(search("a"), ([], False))

    def test_highlight_escapes(self):
        self.assertEqual(
            str(highlight("<b>Pluit</b> pluit", "pluit")),
            "&lt;b&gt;<mark>Pluit</mark>&lt;/b&gt; <mark>pluit</mark>",
        )

    def test_page_and_fragment(self):
        make_published_version(self.author, self.project)
        url = reverse("translations:concordance")
        response = self.client.get(url, {"q": "manemus"})
        self.assertContains(response, "<mark>manemus</mark>", html=False)
        response = self.client.get(url, {"q": "manemus", "fragment": "1"})
        self.assertNotContains(response, "<h1>")
        self.assertContains(response, "Nous restons à la maison.")
