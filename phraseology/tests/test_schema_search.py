from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from phraseology.frequency import schema_matches, slot_fillers
from phraseology.schema import SLOT, Edge, parse_schema

from .test_frequency import AnalysedCorpusTestCase


class SlotTests(SimpleTestCase):
    def test_a_query_may_leave_one_lemma_open(self):
        edges = parse_schema("capio -obj-> *", slot=True)
        self.assertEqual(edges, [Edge("capio", ("obj",), SLOT)])
        edges = parse_schema("capio -obj-> consilium; consilium -amod-> *", slot=True)
        self.assertEqual(edges[1].dependent, SLOT)

    def test_slots_are_for_queries_only_and_one_at_a_time(self):
        cases = {
            ("capio -obj-> *", False): "slot",
            ("capio -obj-> *; capio -obl-> *", True): "two_slots",
            ("* -obj-> consilium", True): "syntax",
        }
        for (text, slot), code in cases.items():
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_schema(text, slot=slot)
            self.assertEqual(caught.exception.code, code)


class SlotMatchesTests(AnalysedCorpusTestCase):
    def test_an_open_lemma_matches_any_dependent(self):
        edges = parse_schema("capio -obj-> *", slot=True)
        matches = schema_matches(edges, self.layer)
        self.assertEqual(matches.count(), 3)
        self.assertEqual(slot_fillers(matches, edges, self.layer), [("consilium", 3)])
        edges = parse_schema("capio -obj-> consilium; consilium -amod-> *", slot=True)
        matches = schema_matches(edges, self.layer)
        self.assertEqual(slot_fillers(matches, edges, self.layer), [("bonus", 1)])


class SchemaSearchPageTests(AnalysedCorpusTestCase):
    url = reverse("phraseology:schema_search")

    def test_the_empty_form(self):
        page = self.client.get(self.url)
        self.assertContains(page, "Recherche par schéma")
        self.assertNotContains(page, "Aucune occurrence")

    def test_occurrences_of_a_schema(self):
        page = self.client.get(self.url, {"schema": "capio -obj|nsubj:pass-> consilium"})
        self.assertContains(page, "3 occurrences repérées automatiquement")
        self.assertContains(page, "Cic. Off. 1, 2")
        page = self.client.get(
            self.url, {"schema": "capio -obj|nsubj:pass-> consilium", "scope": "all"}
        )
        self.assertContains(page, "4 occurrences repérées automatiquement")
        self.assertContains(page, "Sénèque")
        page = self.client.get(
            self.url,
            {"schema": "capio -obj|nsubj:pass-> consilium", "scope": "all", "text_forms": "verse"},
        )
        self.assertContains(page, "Schéma introuvable dans le corpus analysé (version")

    def test_the_lemmas_of_an_open_slot(self):
        page = self.client.get(self.url, {"schema": "capio -obj-> *"})
        self.assertContains(page, "Lemmes de la case vide")
        self.assertContains(page, "?schema=capio+-obj-%3E+consilium")
        self.assertContains(page, "<td>3</td>", html=True)

    def test_an_absence_and_an_invalid_schema(self):
        page = self.client.get(self.url, {"schema": "capio -obl-> consilium"})
        self.assertContains(page, "Schéma introuvable dans le corpus analysé (version")
        self.assertContains(page, "La recherche portait sur le noyau seulement.")
        page = self.client.get(self.url, {"schema": "capio -objet-> consilium"})
        self.assertContains(page, "Relation syntaxique inconnue")
        self.assertNotContains(page, "Aucune occurrence")

    def test_the_unit_page_links_to_its_schema(self):
        self.unit.schema = "capio -obj-> consilium"
        self.unit.save()
        self.client.force_login(self.author)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, f"{self.url}?schema=capio%20-obj-%3E%20consilium&amp;scope=all")
