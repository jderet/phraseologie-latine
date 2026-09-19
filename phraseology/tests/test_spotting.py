from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from phraseology.models import Unit, UnitForm
from phraseology.services import update_unit
from phraseology.spotting import closest_positions, spot_units
from translations.services import save_translation
from translations.tests.factories import make_project, make_source_text, make_version

from .factories import make_abstract_word, make_unit, set_status
from .test_frequency import AnalysedCorpusTestCase


class SpottingTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        update_unit(self.unit, self.author)

    def spotted(self, text, user=None):
        return [spot.unit for spot in spot_units(text, user or self.author)[1]]


class SpottingTests(SpottingTestCase):
    def forms(self, lemma):
        return set(
            UnitForm.objects.filter(unit=self.unit, lemma=lemma).values_list("norm", flat=True)
        )

    def test_forms_come_from_the_analysed_corpus(self):
        self.assertEqual(self.forms("capio"), {"capio", "cepit", "capiunt", "capitur"})
        self.assertEqual(self.forms("consilium"), {"consilium", "consilia"})

    def test_a_unit_is_found_by_the_forms_of_its_words(self):
        _tokens, (spot,) = spot_units("Hodie cōnsilia capiunt.", self.author)
        self.assertEqual(spot.unit, self.unit)
        self.assertEqual((spot.positions, spot.words), ([1, 2], ["cōnsilia", "capiunt"]))
        self.assertEqual(spot.sense.definition, "prendre une décision")
        self.assertEqual(len(spot.attestations), 1)
        self.assertEqual(self.spotted("Consilium cepimus."), [])
        self.assertEqual(self.spotted("Consilium a b c d cepit."), [self.unit])
        self.assertEqual(self.spotted("Consilium a b c d e f g cepit."), [])

    def test_the_word_of_an_optional_relation_is_not_needed(self):
        self.unit.schema = "capio -obj-> consilium; consilium -(amod)-> bonus"
        update_unit(self.unit, self.author)
        self.assertEqual(self.forms("bonus"), set())
        self.assertEqual(self.spotted("Consilium cepit."), [self.unit])

    def test_the_forms_of_an_abstract_word_stand_for_it(self):
        make_abstract_word(self.author, "decisio", [{"lemmas": ["consilium", "ratio"]}])
        self.unit.schema = "capio -obj-> {decisio}"
        update_unit(self.unit, self.author)
        self.assertEqual(self.forms("{decisio}"), {"consilium", "consilia", "ratio"})
        self.assertEqual(self.spotted("Consilia capiunt."), [self.unit])
        self.assertEqual(self.spotted("Capiunt."), [])

    def test_an_abstract_word_known_by_more_than_its_lemmas_is_not_needed(self):
        make_abstract_word(self.author, "res", [{"lemmas": ["consilium"]}, {"upos": ["NOUN"]}])
        self.unit.schema = "capio -obj-> {res}"
        update_unit(self.unit, self.author)
        self.assertEqual(self.forms("{res}"), set())
        self.assertEqual(self.spotted("Capiunt."), [self.unit])

    def test_a_unit_without_schema_does_not_look_for_its_abstract_word(self):
        unit = make_unit(self.author, self.more_words[:2], reference_form="quid {res} multa")
        self.assertEqual(self.spotted("Quid multa? Venit."), [unit])

    def test_drafts_are_found_by_their_creator_only(self):
        self.assertEqual(self.spotted("Consilium cepit.", self.other), [])
        set_status(self.unit, Unit.Status.PROPOSED)
        self.assertEqual(self.spotted("Consilium cepit.", self.other), [self.unit])

    def test_a_unit_without_schema_is_found_by_its_reference_form(self):
        unit = make_unit(self.author, self.more_words[:2], reference_form="Quid multa?")
        self.assertEqual(self.spotted("Quid multa? Venit."), [unit])

    def test_closest_positions(self):
        self.assertEqual(closest_positions([[0, 9], [8]]), (1, [8, 9]))
        self.assertIsNone(closest_positions([[3], [3]]))

    def test_the_refresh_command(self):
        UnitForm.objects.all().delete()
        output = StringIO()
        call_command("refresh_units", stdout=output)
        self.assertIn("1 unité mise à jour", output.getvalue())
        self.assertEqual(self.forms("consilium"), {"consilium", "consilia"})


class SentencePanelTests(SpottingTestCase):
    def setUp(self):
        super().setUp()
        source = make_source_text(self.author, sentences=("Ils décident vite.",))
        self.version = make_version(self.author, make_project(self.author, source))
        self.segment = source.segments.get()
        save_translation(self.version, self.segment, "Consilium celeriter cepit.", self.author)
        self.url = reverse("phraseology:units_in_sentence", args=[self.version.pk, self.segment.pk])

    def test_the_panel_of_the_editor(self):
        self.client.force_login(self.author)
        editor = self.client.get(reverse("translations:version_edit", args=[self.version.pk]))
        self.assertContains(editor, f'data-units-url="{self.url}"')
        response = self.client.get(self.url, {"fragment": "1"})
        self.assertContains(response, "<mark>Consilium</mark> celeriter <mark>cepit</mark>.")
        self.assertContains(response, "consilium capere")
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertNotContains(response, "<html")
        self.assertContains(self.client.get(self.url), "Unités connues dans la phrase 1")

    def test_a_draft_version_stays_private(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_the_sentence_is_escaped(self):
        save_translation(self.version, self.segment, "<b>Consilium</b> cepit.", self.author)
        self.client.force_login(self.author)
        response = self.client.get(self.url, {"fragment": "1"})
        self.assertNotContains(response, "<b>")
        self.assertContains(response, "&lt;")
