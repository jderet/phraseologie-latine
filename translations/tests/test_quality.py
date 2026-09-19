from django.test import SimpleTestCase
from django.urls import reverse

from translations import glossary, qa
from translations.models import GlossaryEntry

from .factories import make_version, translate
from .test_versions import TranslationTestCase


def codes(source, latin):
    return [alert.code for alert in qa.check_sentence(source, latin)]


class SentenceCheckTests(SimpleTestCase):
    def test_a_clean_sentence(self):
        self.assertEqual(codes("Il pleut.", "Pluit."), [])

    def test_identical(self):
        self.assertIn(qa.IDENTICAL, codes("Roma", "Rōma"))

    def test_final_question_mark(self):
        self.assertIn(qa.END, codes("Pleut-il ?", "Pluit."))
        self.assertNotIn(qa.END, codes("Pleut-il ?", "Pluitne?"))

    def test_numbers(self):
        self.assertIn(qa.NUMBERS, codes("En 1492 il partit.", "Anno 1942 profectus est."))
        self.assertNotIn(qa.NUMBERS, codes("En 1492 il partit.", "Anno MCDXCII profectus est."))

    def test_brackets_and_spaces(self):
        self.assertIn(qa.BRACKETS, codes("Il dit (bien).", "Dixit (bene."))
        self.assertIn(qa.SPACES, codes("Il pleut.", "Pluit ."))

    def test_length(self):
        self.assertIn(qa.LENGTH, codes("Nous restons tous à la maison ce soir.", "Manemus."))

    def test_macron_variants(self):
        variants = qa.macron_variants(["Rōma magna.", "Roma parva."])
        self.assertEqual(variants, {"roma": {"rōma", "roma"}})


class QualityTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version, ("Pluit .", "Domi manemus."))
        self.client.force_login(self.author)
        self.url = reverse("translations:quality_report", args=[self.version.pk])

    def test_glossary_term_missing(self):
        glossary.propose_term(
            GlossaryEntry(project=self.project, source_term="maison", latin_term="aedēs"),
            self.author,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "terme du glossaire absent")

    def test_report_and_ignore(self):
        response = self.client.get(self.url)
        self.assertContains(response, "espace avant une ponctuation")
        self.client.post(self.url, {"phrase": self.first.pk, "code": qa.SPACES})
        self.assertNotContains(self.client.get(self.url), "espace avant une ponctuation")

    def test_editor_badge_and_filter(self):
        editor = reverse("translations:version_edit", args=[self.version.pk])
        response = self.client.get(editor, {"filtre": "alertes"})
        self.assertEqual([row["number"] for row in response.context["shown_rows"]], [1])
        self.assertContains(response, 'class="alert-badge"')

    def test_report_for_writers_only(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
