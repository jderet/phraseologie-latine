from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from phraseology.schema import Edge, format_schema, parse_schema, schema_lemmas


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
        edges = parse_schema("memoria -case-> in; redigo -obl-> memoria")
        self.assertEqual(format_schema(edges), "redigo -obl-> memoria; memoria -case-> in")
        self.assertEqual(schema_lemmas(edges), ["redigo", "memoria", "in"])

    def test_an_empty_schema(self):
        self.assertEqual(parse_schema(" ; "), [])

    def test_invalid_schemas(self):
        cases = {
            "capio obj consilium": "syntax",
            "capio -objet-> consilium": "relation",
            "capio -obj-> consilium; do -obj-> consilium": "two_heads",
            "capio -obj-> consilium; do -obj-> operam": "tree",
            "a -obj-> b; b -obj-> a": "tree",
            "a -obj-> b; a -obl-> c; a -amod-> d; a -nmod-> e; a -advmod-> f": "too_many",
        }
        for text, code in cases.items():
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_schema(text)
            self.assertEqual(caught.exception.code, code)
