from corpus.models import Author
from justifications.tests.factories import make_passage
from phraseology.frequency import count_by_author, occurrence_tokens, schema_matches
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

    def test_count_by_author(self):
        matches = schema_matches(parse_schema("capio -obj|nsubj:pass-> consilium"), self.layer)
        rows = [(author.cts_id, total, core) for author, total, core in count_by_author(matches)]
        self.assertEqual(rows, [("phi1017", 1, 0), ("phi0474", 3, 3)])


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
