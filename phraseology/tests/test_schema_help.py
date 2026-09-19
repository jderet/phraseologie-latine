from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from corpus.tests.test_timeouts import canceled_query
from justifications.tests.factories import make_passage
from phraseology.schema import RELATION_CHOICES, RELATIONS
from phraseology.schema_help import MAX_WORDS, check_schema, lemma_choices, written_words
from phraseology.tests.factories import analyze

from .test_frequency import AnalysedCorpusTestCase


class RelationChoicesTests(SimpleTestCase):
    def test_every_relation_but_the_root_is_offered_once(self):
        codes = [code for code, _label, _common in RELATION_CHOICES]
        self.assertEqual(len(codes), len(set(codes)))
        # The preposition is linked by the prepositional phrase and its regime, not by case.
        self.assertEqual(
            {code.split(":")[0] for code in codes}, RELATIONS - {"root", "case"} | {"sp", "reg"}
        )
        self.assertEqual(codes[0], "obj")

    def test_written_words(self):
        self.assertEqual(written_words("in memoriam, redigere !"), ["in", "memoriam", "redigere"])
        self.assertEqual(len(written_words("a b c d e f g h i")), MAX_WORDS)
        self.assertEqual(written_words(""), [])


class LemmaChoicesTests(AnalysedCorpusTestCase):
    def test_lemmas_come_from_the_analysis_the_most_frequent_first(self):
        _passage, words = make_passage(("Est", "est", "est."), reference="1.4")
        for word, lemma in zip(words, ("sum", "edo", "sum"), strict=True):
            analyze(self.layer, word, lemma)
        self.assertEqual(
            lemma_choices("Est", self.layer),
            {"form": "Est", "lemmas": ["sum", "edo"], "known": True},
        )
        self.assertEqual(lemma_choices("cēpit", self.layer)["lemmas"], ["capio"])

    def test_a_lemma_and_an_unknown_word(self):
        self.assertEqual(
            lemma_choices("capio", self.layer),
            {"form": "capio", "lemmas": ["capio"], "known": True},
        )
        self.assertEqual(
            lemma_choices("Vélo", self.layer), {"form": "Vélo", "lemmas": ["uelo"], "known": False}
        )

    def test_the_page_of_lemmas(self):
        response = self.client.get(
            reverse("phraseology:schema_lemmas"), {"formes": "consilium capere, 3"}
        )
        words = response.json()["words"]
        self.assertEqual([word["form"] for word in words], ["consilium", "capere"])
        self.assertEqual(words[0]["lemmas"], ["consilium"])
        self.assertFalse(words[1]["known"])
        self.assertEqual(self.client.post(reverse("phraseology:schema_lemmas")).status_code, 405)


class CheckSchemaTests(AnalysedCorpusTestCase):
    def test_a_schema_in_its_written_form(self):
        result = check_schema("consilium -amod-> bonus; Capiō —obj → cōnsilium")
        self.assertEqual(result["text"], "capio -obj-> consilium; consilium -amod-> bonus")
        self.assertEqual(
            result["edges"][0],
            {"head": "capio", "relations": ["obj"], "dependent": "consilium", "optional": False},
        )
        self.assertEqual(result["errors"], [])
        self.assertNotIn("core", result)

    def test_an_optional_relation(self):
        result = check_schema("capio -obj-> consilium; consilium -(amod)-> bonus", count=True)
        self.assertEqual(result["text"], "capio -obj-> consilium; consilium -(amod)-> bonus")
        self.assertIs(result["edges"][1]["optional"], True)
        self.assertEqual(result["core"], 3)

    def test_errors(self):
        self.assertIn(
            "Écrivez chaque relation ainsi", check_schema("capio obj consilium")["errors"][0]
        )
        self.assertTrue(check_schema("capio -obj-> *")["errors"])
        self.assertEqual(check_schema("capio -obj-> *", slot=True)["errors"], [])
        self.assertIn("300 caractères", check_schema("a" * 301)["errors"][0])

    def test_occurrences_in_the_core(self):
        result = check_schema("capio -obj|nsubj:pass-> consilium", count=True)
        self.assertEqual(result["core"], 3)
        self.assertIn(reverse("phraseology:schema_search"), result["search_url"])
        self.assertNotIn("version", result)
        absent = check_schema("capio -obl-> consilium", count=True)
        self.assertEqual(absent["core"], 0)
        self.assertIn("LatinCy test 1.0", absent["version"])

    def test_a_count_too_long(self):
        with mock.patch("phraseology.schema_help.schema_matches", side_effect=canceled_query):
            result = check_schema("capio -obj-> consilium", count=True)
        self.assertEqual((result["core"], result["exceeded"]), (None, True))

    def test_the_page_of_a_schema(self):
        url = reverse("phraseology:schema_check")
        result = self.client.get(url, {"schema": "capio -obj-> *", "case_vide": "1"}).json()
        self.assertEqual(result["text"], "capio -obj-> *")
        result = self.client.get(url, {"schema": "capio -obj-> consilium", "compter": "1"}).json()
        self.assertEqual(result["core"], 3)
        self.assertTrue(self.client.get(url, {"schema": "capio -obj-> *"}).json()["errors"])
