from django.core.exceptions import PermissionDenied
from django.urls import reverse

from translations import glossary
from translations.models import GlossaryEntry

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class GlossaryTestCase(TranslationTestCase):
    def term(self, source="maison", latin="domus", author=None):
        entry = GlossaryEntry(project=self.project, source_term=source, latin_term=latin)
        return glossary.propose_term(entry, author or self.other)


class GlossaryServiceTests(GlossaryTestCase):
    def test_proposed_then_adopted_by_the_creator(self):
        entry = self.term()
        self.assertEqual(entry.status, "proposed")
        glossary.decide_term(entry, self.author, adopt=True)
        entry.refresh_from_db()
        self.assertTrue(entry.is_adopted)

    def test_the_creator_adds_adopted_terms(self):
        self.assertTrue(self.term(author=self.author).is_adopted)

    def test_others_may_not_decide(self):
        entry = self.term()
        with self.assertRaises(PermissionDenied):
            glossary.decide_term(entry, self.other, adopt=True)

    def test_terms_are_found_as_whole_words_without_accents_or_case(self):
        entries = [self.term("État", "cīvitās"), self.term("mer", "mare")]
        found = glossary.find_terms("L’etat de la mer. Merci.", entries)
        self.assertEqual([item.entry.latin_term for item in found], ["cīvitās", "mare"])

    def test_marked_text_is_escaped(self):
        entries = [self.term("<b>", "x")]
        text = str(glossary.marked_text("a <b> b", entries))
        self.assertNotIn("<b>", text.replace('data-use-latin="x"', ""))

    def test_latin_present_allows_inflection(self):
        entry = GlossaryEntry(latin_term="rēs pūblica")
        self.assertTrue(glossary.latin_present("Rem publicam administrat.", entry))
        self.assertFalse(glossary.latin_present("Civitatem administrat.", entry))


class GlossaryPageTests(GlossaryTestCase):
    def test_propose_from_the_page(self):
        self.client.force_login(self.other)
        url = reverse("translations:glossary", args=[self.project.pk])
        response = self.client.post(url, {"source_term": "pluie", "latin_term": "imber"})
        self.assertRedirects(response, url)
        self.assertContains(self.client.get(url), "imber")

    def test_editor_marks_adopted_terms(self):
        self.term("maison", "domus", author=self.author)
        version = make_version(self.author, self.project)
        translate(version)
        self.client.force_login(self.author)
        response = self.client.get(reverse("translations:version_edit", args=[version.pk]))
        self.assertContains(response, '<mark class="term" title="→ domus"', html=False)
        panel = self.client.get(
            reverse("translations:editor_glossary", args=[version.pk, self.second.pk])
        )
        self.assertContains(panel, "domus")

    def test_link_to_an_invisible_unit_is_refused(self):
        self.client.force_login(self.other)
        url = reverse("translations:glossary", args=[self.project.pk])
        response = self.client.post(
            url, {"source_term": "pluie", "latin_term": "imber", "unit_number": 999999}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GlossaryEntry.objects.exists())
