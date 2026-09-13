import importlib.util
import io
import re
from types import SimpleNamespace
from unittest import skipUnless

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from corpus.analysis import AnalyzedToken, Chunk, align, build_chunks, offset_map
from corpus.models import AnalysisLayer, Token, TokenAnalysis
from corpus.text import normalize

from .utils import PerseusSourceMixin

FAKE_ANALYZER = "corpus.tests.test_analysis.FakeAnalyzer"
LEMMAS = {"cepit": "capio", "athenis": "Athenae", "iam": "iam"}


class FakeAnalyzer:
    """A tiny analyser behaving like LatinCy: punctuation tokens, -que split off."""

    tool = "Fake analyser"
    tool_version = "1.0"
    details = {}

    def __init__(self, model):
        self.model = model

    def analyze(self, texts):
        for text in texts:
            yield self._analyze(text)

    def _analyze(self, text):
        items, sentence, root = [], 0, None
        for match in re.finditer(r"\w+|[^\w\s]", text):
            word = match.group()
            if not word[0].isalnum():
                items.append(AnalyzedToken(match.start(), word, word, "PUNCT", sentence=sentence))
                if word in ".?!":
                    sentence, root = sentence + 1, None
                continue
            pieces = [(match.start(), word)]
            if len(word) > 5 and word.lower().endswith("que"):
                pieces = [(match.start(), word[:-3]), (match.end() - 3, "que")]
            for start, piece in pieces:
                items.append(
                    AnalyzedToken(
                        start=start,
                        text=piece,
                        lemma=LEMMAS.get(piece.lower(), piece.lower()),
                        upos="X",
                        deprel="root" if root is None else "dep",
                        head=root,
                        sentence=sentence,
                    )
                )
                if root is None:
                    root = len(items) - 1
        return items


class AlignmentTests(SimpleTestCase):
    def test_enclitics_become_parts_and_punctuation_is_left_aside(self):
        chunk = Chunk("senatusque, populus.", [(1, 0, 10), (2, 12, 19)])
        analyzed = [
            AnalyzedToken(0, "senatus"),
            AnalyzedToken(7, "que"),
            AnalyzedToken(10, ","),
            AnalyzedToken(12, "populus"),
            AnalyzedToken(19, "."),
        ]
        self.assertEqual(align(chunk, analyzed), {0: (1, 0), 1: (1, 1), 3: (2, 0)})

    def test_offsets_are_realigned_when_the_analyser_changes_the_length_of_the_text(self):
        self.assertIsNone(offset_map("ut videmur", "ut uidemur"))
        original, produced = "Cæsar venit", "Caesar uenit"
        mapping = offset_map(original, produced)
        self.assertEqual(mapping[produced.index("uenit")], original.index("venit"))
        self.assertEqual(mapping[0], 0)

    def test_chunks_are_made_of_whole_passages_and_keep_word_positions(self):
        tokens = [
            SimpleNamespace(id=1, passage_id=10, before="«", form="quid", after=" "),
            SimpleNamespace(id=2, passage_id=10, before="", form="multa", after="?»"),
            SimpleNamespace(id=3, passage_id=11, before="", form="Vale", after="."),
        ]
        chunks = list(build_chunks(tokens, max_characters=5))
        self.assertEqual([chunk.text for chunk in chunks], ["«quid multa?»", "Vale."])
        self.assertEqual(chunks[0].words, [(1, 1, 5), (2, 6, 11)])
        (single,) = build_chunks(tokens)
        self.assertEqual(single.text, "«quid multa?»\nVale.")
        self.assertEqual(single.text[14:18], "Vale")
        self.assertEqual(single.words[2], (3, 14, 18))


class AnalyzeCorpusTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def analyze(self, *arguments):
        output = io.StringIO()
        call_command("analyze_corpus", "--analyzer", FAKE_ANALYZER, *arguments, stdout=output)
        return output.getvalue()

    def test_every_word_is_analysed_in_a_new_layer(self):
        self.analyze("--make-default")
        layer = AnalysisLayer.objects.get()
        self.assertTrue(layer.is_default)
        self.assertEqual(layer.editions.count(), 4)
        self.assertEqual(TokenAnalysis.objects.filter(part=0).count(), Token.objects.count())
        cepit = TokenAnalysis.objects.get(token__form="cepit")
        self.assertEqual(
            (cepit.lemma_norm, cepit.head.form, cepit.deprel), ("capio", "consilium", "dep")
        )
        self.assertEqual(TokenAnalysis.objects.get(token__form="consilium").sentence, 1)

    def test_an_enclitic_is_a_second_part_of_the_same_word(self):
        self.analyze()
        parts = TokenAnalysis.objects.filter(token__form="virumque").order_by("part")
        self.assertEqual(list(parts.values_list("part", "text")), [(0, "virum"), (1, "que")])

    def test_layers_are_versioned_and_can_be_completed(self):
        self.analyze("--work", "phi0474.phi055")
        first = AnalysisLayer.objects.get()
        self.assertEqual(first.editions.count(), 1)
        output = self.analyze("--layer", str(first.pk))
        self.assertIn("déjà analysée", output)
        self.assertEqual(first.editions.count(), 4)
        self.analyze("--make-default")
        self.assertEqual(AnalysisLayer.objects.count(), 2)
        first.make_default()
        self.assertEqual(list(AnalysisLayer.objects.filter(is_default=True)), [first])

    def test_errors(self):
        with self.assertRaises(CommandError):
            self.analyze("--work", "phi9999.phi001")
        with self.assertRaises(CommandError):
            call_command("analyze_corpus", "--analyzer", "corpus.tests.test_analysis.Missing")


@skipUnless(importlib.util.find_spec("la_core_web_lg"), "LatinCy is not installed")
class LatinCyTests(SimpleTestCase):
    def test_lemmas_of_consilium_capere(self):
        from corpus.analysis import SpacyAnalyzer

        (tokens,) = SpacyAnalyzer().analyze(["Caesar consilium cepit."])
        lemmas = {token.text: normalize(token.lemma) for token in tokens}
        self.assertEqual(lemmas["consilium"], "consilium")
        self.assertEqual(lemmas["cepit"], "capio")
