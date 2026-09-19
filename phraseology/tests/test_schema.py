from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from phraseology.schema import (
    Edge,
    corpus_edges,
    format_schema,
    parse_schema,
    required_edges,
    schema_abstracts,
    schema_lemmas,
    schema_nodes,
)


class SchemaTests(SimpleTestCase):
    def test_one_relation(self):
        edges = parse_schema("capio -obj-> consilium")
        self.assertEqual(edges, [Edge("capio", ("obj",), "consilium")])
        self.assertEqual(format_schema(edges), "capio -obj-> consilium")
        self.assertEqual(edges[0].label, "capio —obj→ consilium")

    def test_lemmas_are_normalized_and_arrows_may_be_typed(self):
        edges = parse_schema("  Gerō —obj | nsubj:pass→ Bellum ")
        self.assertEqual(edges, [Edge("gero", ("obj", "nsubj:pass"), "bellum")])
        self.assertEqual(format_schema(edges), "gero -obj|nsubj:pass-> bellum")

    def test_a_tree_starts_from_its_root(self):
        edges = parse_schema("res -amod-> publicus; gero -obj-> res")
        self.assertEqual(format_schema(edges), "gero -obj-> res; res -amod-> publicus")
        self.assertEqual(schema_lemmas(edges), ["gero", "res", "publicus"])

    def test_an_empty_schema(self):
        self.assertEqual(parse_schema(" ; "), [])

    def test_a_prepositional_phrase_has_the_preposition_first(self):
        edges = parse_schema("de -reg:abl-> res; mereor -sp-> de; mereor -advmod-> bene")
        self.assertEqual(
            format_schema(edges), "mereor -sp-> de; mereor -advmod-> bene; de -reg:abl-> res"
        )
        self.assertEqual(schema_lemmas(edges), ["mereor", "de", "bene", "res"])
        self.assertEqual([edge.kind for edge in edges], ["sp", "", "reg"])

    def test_the_phrase_written_as_the_analysis_gives_it_is_rewritten(self):
        cases = {
            "memoria -case-> in; redigo -obl-> memoria": "redigo -sp-> in; in -reg-> memoria",
            "liber -nmod:x-> amicitia; amicitia -case-> de": "liber -sp-> de; de -reg-> amicitia",
            "memoria -case-> in": "in -reg-> memoria",
            # Another relation than obl or nmod is kept as it is written.
            "redigo -advmod-> memoria; memoria -case-> in": (
                "redigo -advmod-> memoria; memoria -case-> in"
            ),
        }
        for text, written in cases.items():
            with self.subTest(text=text):
                self.assertEqual(format_schema(parse_schema(text)), written)

    def test_the_analysis_is_looked_for_as_it_is_written(self):
        edges = parse_schema("mereor -sp-> de; de -reg:abl-> res; res -amod-> publicus")
        written, cases = corpus_edges(edges)
        self.assertEqual(
            format_schema(written),
            "mereor -obl|nmod-> res; res -case-> de; res -amod-> publicus",
        )
        self.assertEqual(cases, {"res": "Abl"})
        written, cases = corpus_edges(parse_schema("de -reg-> *", slot=True))
        self.assertEqual((format_schema(written), cases), ("* -case-> de", {}))
        self.assertEqual(corpus_edges(written), (written, {}))

    def test_an_optional_relation_is_written_between_parentheses(self):
        edges = parse_schema("gero -obj-> bellum; gero - ( sp ) -> cum; cum -reg-> aliquis")
        self.assertEqual(
            format_schema(edges), "gero -obj-> bellum; gero -(sp)-> cum; cum -reg-> aliquis"
        )
        self.assertEqual([edge.optional for edge in edges], [False, True, False])
        self.assertEqual(edges[1].label, "gero —(sp)→ cum")
        self.assertEqual(format_schema(parse_schema(format_schema(edges))), format_schema(edges))

    def test_the_required_relations_leave_out_what_hangs_on_an_optional_one(self):
        edges = parse_schema("gero -obj-> bellum; gero -(sp)-> cum; cum -reg-> aliquis")
        self.assertEqual(format_schema(required_edges(edges)), "gero -obj-> bellum")
        edges = parse_schema("capio -obj-> consilium; consilium -(amod)-> bonus")
        self.assertEqual(format_schema(required_edges(edges)), "capio -obj-> consilium")

    def test_an_optional_phrase_written_as_the_analysis_gives_it(self):
        edges = parse_schema("gero -obj-> bellum; gero -(obl)-> aliquis; aliquis -case-> cum")
        self.assertEqual(
            format_schema(edges), "gero -obj-> bellum; gero -(sp)-> cum; cum -reg-> aliquis"
        )
        written, _cases = corpus_edges(edges)
        self.assertEqual(
            format_schema(written),
            "gero -obj-> bellum; gero -(obl|nmod)-> aliquis; aliquis -case-> cum",
        )

    def test_an_abstract_word_between_braces(self):
        edges = parse_schema("Sūmō -obj-> { Liquide }; {liquide} -(amod)-> frigidus")
        self.assertEqual(
            format_schema(edges), "sumo -obj-> {liquide}; {liquide} -(amod)-> frigidus"
        )
        self.assertEqual(schema_lemmas(edges), ["sumo", "frigidus"])
        self.assertEqual(schema_nodes(edges), ["sumo", "{liquide}", "frigidus"])
        self.assertEqual(schema_abstracts(edges), ["liquide"])
        # Two different abstract words, and the regime of a phrase.
        edges = parse_schema("causa -nmod-> {possesseur}; causa -sp-> in; in -reg-> {lieu}")
        self.assertEqual(schema_abstracts(edges), ["possesseur", "lieu"])
        written, _cases = corpus_edges(edges)
        self.assertEqual(written[0].head, "causa")

    def test_invalid_schemas(self):
        cases = {
            "capio obj consilium": "syntax",
            "capio -objet-> consilium": "relation",
            "capio -obj-> consilium; do -obj-> consilium": "two_heads",
            "capio -obj-> consilium; do -obj-> operam": "tree",
            "a -obj-> b; b -obj-> a": "tree",
            "a -obj-> b; a -obl-> c; a -amod-> d; a -nmod-> e; a -advmod-> f": "too_many",
            "mereor -sp:de-> de; de -reg-> res": "relation",
            "in -reg:dat-> memoria": "relation",
            "mereor -sp|obl-> de; de -reg-> res": "phrase_variant",
            "mereor -sp-> de": "no_regime",
            "mereor -sp-> de; de -amod-> res": "no_regime",
            "mereor -obj-> de; de -reg-> res": "regime",
            "in -reg-> memoria; in -advmod-> non": "regime",
            "capio -(obj)-> consilium": "all_optional",
            "gero -(obj)-> bellum; gero -(sp)-> cum; cum -reg-> aliquis": "all_optional",
            "gero -obj-> bellum; gero -sp-> cum; cum -(reg)-> aliquis": "optional_regime",
            "capio -(obj-> consilium": "syntax",
            "{liquide} -amod-> frigidus": "abstract_root",
            # The regime of a phrase at the root is the word looked for.
            "in -reg-> {lieu}": "abstract_root",
            "sumo -obj-> {liquidé}": "abstract_name",
            "sumo -obj-> {}": "abstract_name",
            "sumo -obj-> {liquide}; sumo -obl-> {liquide}": "two_abstract",
            "sumo -obj-> {liquide": "syntax",
        }
        for text, code in cases.items():
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_schema(text)
            self.assertEqual(caught.exception.code, code)
