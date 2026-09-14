from django.urls import reverse

from phraseology.annotation import guess_schema, search_units, suggested_units
from phraseology.models import Attestation, Unit
from phraseology.schema import format_schema, parse_schema
from phraseology.services import propose_unit, set_example, update_unit

from .test_frequency import AnalysedCorpusTestCase

SCHEMA = "capio -obj|nsubj:pass-> consilium"


def written(schema):
    return format_schema(parse_schema(schema))


def ids(words):
    return ",".join(str(word.pk) for word in words)


class AnnotationTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = SCHEMA
        update_unit(self.unit, self.author)
        propose_unit(self.unit, self.author)
        self.unit.refresh_from_db()
        self.reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])


class SuggestionTests(AnnotationTestCase):
    def test_the_schema_guessed_from_the_analysis(self):
        self.assertEqual(guess_schema(self.words[:2], self.layer), written(SCHEMA))
        tree = written(f"{SCHEMA}; consilium -amod-> bonus")
        self.assertEqual(guess_schema(self.good_words, self.layer), tree)
        self.assertEqual(guess_schema(self.words[1:3], self.layer), "")
        self.assertEqual(guess_schema(self.words[:1], self.layer), "")

    def test_units_suggested_and_searched(self):
        self.assertEqual(suggested_units(self.other, self.more_words[:2]), [self.unit])
        self.assertEqual(suggested_units(self.other, self.words[2:4]), [])
        self.assertEqual(search_units(self.other, "consilium"), [self.unit])
        self.assertEqual(search_units(self.other, " "), [])


class AnnotationViewTests(AnnotationTestCase):
    def test_the_panel_of_the_chosen_words(self):
        url = reverse("phraseology:annotate_selection")
        chosen = {"mots": ids(self.more_words[:2]), "fragment": "1"}
        self.assertEqual(self.client.get(url, chosen).status_code, 302)
        self.client.force_login(self.other)
        response = self.client.get(url, {**chosen, "retour": f"{self.reading}#p-1.2"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, f'name="unit" value="{self.unit.pk}"')
        self.assertContains(response, f'name="next" value="{self.reading}#p-1.2"')
        self.assertContains(response, "schema=capio")
        searched = self.client.get(url, {"mots": ids(self.words[2:4]), "q": "consilium"})
        self.assertContains(searched, "<html")
        self.assertContains(searched, f'name="unit" value="{self.unit.pk}"')
        wrong = self.client.get(url, {"mots": "abc", "fragment": "1"})
        self.assertContains(wrong, "errorlist")

    def test_the_words_are_attached_to_a_unit(self):
        self.client.force_login(self.other)
        attach = reverse("phraseology:annotate_attach")
        back = f"{self.reading}#p-1.2"
        data = {
            "unit": self.unit.pk,
            "words": ids(self.more_words[:2]),
            "note": "au pluriel",
            "example_proposed": "on",
            "next": back,
        }
        self.assertRedirects(self.client.post(attach, data), back, fetch_redirect_response=False)
        attestation = self.unit.attestations.get(passage=self.second_passage)
        self.assertEqual(
            (attestation.created_by, attestation.status, attestation.note),
            (self.other, Attestation.Status.PROPOSED, "au pluriel"),
        )
        self.assertTrue(attestation.example_proposed)
        response = self.client.post(attach, {**data, "next": "https://example.com/"}, follow=True)
        self.assertContains(response, "Ces mots attestent déjà cette fiche.")
        set_example(attestation, self.reviewer, True)
        attestation.refresh_from_db()
        self.assertTrue(attestation.is_example)
        self.assertFalse(attestation.example_proposed)

    def test_the_mode_annoter_of_the_reading(self):
        self.assertNotContains(self.client.get(self.reading), "Annoter</a>")
        self.client.force_login(self.other)
        response = self.client.get(self.reading)
        self.assertContains(response, f'href="{self.reading}?annoter=1"')
        self.assertContains(response, 'data-annotating=""')
        annotating = self.client.get(self.reading, {"annoter": "1"})
        self.assertContains(annotating, 'data-annotating="1"')
        self.assertContains(annotating, "Mode annoter")
        self.assertContains(annotating, 'name="annoter" value="1"')
        self.assertContains(annotating, f'<a href="{self.reading}" class="button">', html=False)

    def test_the_draft_of_someone_else_cannot_be_attested(self):
        Unit.objects.filter(pk=self.unit.pk).update(status=Unit.Status.DRAFT)
        self.client.force_login(self.other)
        attach = reverse("phraseology:annotate_attach")
        response = self.client.post(attach, {"unit": self.unit.pk, "words": ids(self.words[:2])})
        self.assertEqual(response.status_code, 404)

    def test_a_new_entry_prefilled_with_the_words(self):
        self.client.force_login(self.other)
        url = reverse("phraseology:unit_create")
        chosen = ids(self.more_words[:2])
        response = self.client.get(
            url, {"forme": "consilia capiunt", "mots": chosen, "schema": SCHEMA}
        )
        self.assertContains(response, 'value="consilia capiunt"')
        self.assertContains(response, f'value="{chosen}" checked')
        data = {
            "reference_form": "consilia capere",
            "schema": SCHEMA,
            "definition": "prendre des décisions",
            "attestation": chosen,
        }
        self.client.post(url, data)
        unit = Unit.objects.get(reference_form="consilia capere")
        self.assertEqual(unit.schema, written(SCHEMA))
        self.assertEqual(unit.frequency.total, 4)
