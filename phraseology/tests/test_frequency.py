from corpus.models import Author
from justifications.tests.factories import make_passage
from phraseology.frequency import count_by_author, occurrence_tokens, schema_matches, slot_fillers
from phraseology.schema import parse_schema
from phraseology.services import current_frequency, refresh_frequency, update_unit
from phraseology.tests.factories import analyze, make_layer, make_outside_passage

from .test_units import PhraseologyTestCase


class AnalysedCorpusTestCase(PhraseologyTestCase):
    """Consilium capere twice in the core (Cicero), once in the passive outside it (Seneca)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.layer = make_layer()
        consilium, cepit = cls.words[:2]
        verb, noun = {"upos": "VERB"}, {"upos": "NOUN"}
        analyze(cls.layer, cepit, "capio", **verb)
        analyze(cls.layer, consilium, "consilium", "obj", cepit, **noun)
        consilia, capiunt = cls.more_words[:2]
        analyze(cls.layer, capiunt, "capio", **verb)
        analyze(cls.layer, consilia, "consilium", "obj", capiunt, **noun)
        _passage, (bonum, consilium_bonum, cepit_bonum) = make_passage(
            ("Bonum", "consilium", "cepit."), reference="1.3"
        )
        analyze(cls.layer, cepit_bonum, "capio", **verb)
        analyze(cls.layer, consilium_bonum, "consilium", "obj:dir", cepit_bonum, **noun)
        analyze(cls.layer, bonum, "bonus", "amod", consilium_bonum, upos="ADJ")
        cls.good_words = (bonum, consilium_bonum, cepit_bonum)
        _passage, (consilium_passive, capitur) = make_outside_passage(("Consilium", "capitur."))
        analyze(cls.layer, capitur, "capio", **verb)
        analyze(cls.layer, consilium_passive, "consilium", "nsubj:pass", capitur, **noun)
        cls.seneca = Author.objects.get(cts_id="phi1017")


class SchemaMatchesTests(AnalysedCorpusTestCase):
    def count(self, schema, core_only=False):
        return schema_matches(parse_schema(schema), self.layer, core_only).count()

    def test_a_relation_matches_its_subtypes(self):
        self.assertEqual(self.count("capio -obj-> consilium"), 3)
        self.assertEqual(self.count("capio -obj:dir-> consilium"), 1)
        self.assertEqual(self.count("capio -nsubj-> consilium"), 1)
        self.assertEqual(self.count("capio -obl-> consilium"), 0)

    def test_alternatives_and_the_core(self):
        self.assertEqual(self.count("capio -obj|nsubj:pass-> consilium"), 4)
        self.assertEqual(self.count("capio -obj|nsubj:pass-> consilium", core_only=True), 3)

    def test_a_tree_of_relations(self):
        edges = parse_schema("capio -obj-> consilium; consilium -amod-> bonus")
        (match,) = schema_matches(edges, self.layer)
        self.assertEqual(occurrence_tokens(match, edges, self.layer), list(self.good_words))

    def test_an_optional_relation_is_not_required(self):
        edges = parse_schema("capio -obj-> consilium; consilium -(amod)-> bonus")
        matches = schema_matches(edges, self.layer)
        self.assertEqual(matches.count(), 3)
        words = [occurrence_tokens(match, edges, self.layer) for match in matches]
        self.assertIn(list(self.good_words), words)
        self.assertEqual(sorted(len(found) for found in words), [2, 2, 3])

    def test_count_by_author(self):
        matches = schema_matches(parse_schema("capio -obj|nsubj:pass-> consilium"), self.layer)
        rows = [(author.cts_id, total, core) for author, total, core in count_by_author(matches)]
        self.assertEqual(rows, [("phi1017", 1, 0), ("phi0474", 3, 3)])


class PrepositionalPhraseTests(PhraseologyTestCase):
    """De re (publica) bene meritus, the noun in obl, nmod or advmod; in memoriam, in memoria."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.layer = make_layer()
        verb = {"upos": "VERB"}
        texts = (
            (("De", "re", "publica", "bene", "meritus."), "obl", "Case=Abl"),
            (("De", "re", "bene", "meritus."), "nmod", ""),
            (("De", "re", "meritus."), "advmod", "Case=Abl"),
        )
        for number, (forms, relation, feats) in enumerate(texts, start=1):
            _passage, words = make_passage(forms, reference=f"3.{number}")
            de, re, meritus = words[0], words[1], words[-1]
            analyze(cls.layer, meritus, "mereor", **verb)
            analyze(cls.layer, re, "res", relation, meritus, upos="NOUN", feats=feats)
            analyze(cls.layer, de, "de", "case", re, upos="ADP")
            if number == 1:
                cls.phrase_words = (de, re, meritus)
                analyze(cls.layer, words[2], "publicus", "amod", re, upos="ADJ")
            if forms[-2] == "bene":
                analyze(cls.layer, words[-2], "bene", "advmod", meritus, upos="ADV")
                cls.well_words = getattr(cls, "well_words", ()) + (words,)
        for number, (noun, case) in enumerate((("memoriam", "Acc"), ("memoria", "Abl")), start=4):
            _passage, (in_, memoria, redegit) = make_passage(
                ("In", noun, "redegit."), reference=f"3.{number}"
            )
            analyze(cls.layer, redegit, "redigo", **verb)
            analyze(cls.layer, memoria, "memoria", "obl", redegit, feats=f"Case={case}")
            analyze(cls.layer, in_, "in", "case", memoria, upos="ADP")

    def count(self, schema):
        return schema_matches(parse_schema(schema, slot=True), self.layer).count()

    def test_the_phrase_depends_on_its_head_by_obl_or_nmod(self):
        self.assertEqual(self.count("mereor -sp-> de; de -reg-> res"), 2)
        self.assertEqual(self.count("mereor -obl-> res; res -case-> de"), 2)
        self.assertEqual(self.count("mereor -sp-> de; de -reg-> res; res -amod-> publicus"), 1)

    def test_the_case_of_the_regime(self):
        self.assertEqual(self.count("mereor -sp-> de; de -reg:abl-> res"), 1)
        self.assertEqual(self.count("redigo -sp-> in; in -reg:acc-> memoria"), 1)
        self.assertEqual(self.count("redigo -sp-> in; in -reg:abl-> memoria"), 1)
        self.assertEqual(self.count("redigo -sp-> in; in -reg-> memoria"), 2)

    def test_a_phrase_alone_and_an_open_regime(self):
        self.assertEqual(self.count("de -reg-> res"), 3)
        edges = parse_schema("mereor -sp-> de; de -reg-> *", slot=True)
        matches = schema_matches(edges, self.layer)
        self.assertEqual(slot_fillers(matches, edges, self.layer), [("res", 2)])

    def test_an_optional_phrase_keeps_its_regime(self):
        edges = parse_schema("mereor -advmod-> bene; mereor -(sp)-> de; de -reg:abl-> res")
        matches = schema_matches(edges, self.layer)
        self.assertEqual(matches.count(), 2)
        words = {match.token_id: occurrence_tokens(match, edges, self.layer) for match in matches}
        (de, re, _publica, bene, meritus), (*_phrase, bene_2, meritus_2) = self.well_words
        # The regime of the first phrase is in the ablative; the second has no case given.
        self.assertEqual(words[meritus.pk], [de, re, bene, meritus])
        self.assertEqual(words[meritus_2.pk], [bene_2, meritus_2])

    def test_the_words_of_an_occurrence(self):
        edges = parse_schema("mereor -sp-> de; de -reg:abl-> res")
        (match,) = schema_matches(edges, self.layer)
        self.assertEqual(occurrence_tokens(match, edges, self.layer), list(self.phrase_words))


class UnitFrequencyTests(AnalysedCorpusTestCase):
    def test_the_frequency_follows_the_schema(self):
        self.assertIsNone(refresh_frequency(self.unit))
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        update_unit(self.unit, self.author)
        frequency = current_frequency(self.unit)
        self.assertEqual((frequency.total, frequency.core_total), (4, 3))
        self.assertEqual(
            frequency.by_author,
            [[self.seneca.pk, 1, 0], [self.words[0].edition.work.author_id, 3, 3]],
        )
        self.assertIn("LatinCy test 1.0", frequency.corpus_version)
        self.unit.schema = "capio -obj-> consilium"
        update_unit(self.unit, self.author)
        self.assertEqual(current_frequency(self.unit).total, 3)
        self.unit.schema = ""
        update_unit(self.unit, self.author)
        self.assertIsNone(current_frequency(self.unit))
