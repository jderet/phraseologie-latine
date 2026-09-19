from django.urls import reverse

from phraseology.composition import components, containers, contains, schema_parts
from phraseology.models import Unit
from phraseology.schema import parse_schema

from .test_units import PhraseologyTestCase

DE_RE_PUBLICA = "mereor -sp-> de; mereor -advmod-> bene; de -reg-> res; res -amod-> publicus"


class ContainsTests(PhraseologyTestCase):
    def test_every_relation_of_the_smaller_schema(self):
        cases = {
            ("gero -obj|nsubj:pass-> res; res -amod-> publicus", "gero -obj-> res"): True,
            ("gero -obj-> res; res -amod-> publicus", "gero -obj|nsubj:pass-> res"): True,
            ("gero -obj-> res; res -amod-> publicus", "gero -nsubj-> res"): False,
            ("redigo -sp-> in; in -reg:abl-> memoria", "in -reg-> memoria"): True,
            ("redigo -sp-> in; in -reg:abl-> memoria", "in -reg:acc-> memoria"): False,
            ("gero -obj-> res; res -amod-> publicus", "res -amod-> publicus"): True,
            # Only required relations count.
            ("gero -obj-> res; res -(amod)-> publicus", "res -amod-> publicus"): False,
            ("gero -obj-> bellum; gero -(sp)-> cum; cum -reg-> aliquis", "gero -obj-> bellum"): (
                False
            ),
            ("gero -obj-> res; gero -(advmod)-> bene; res -amod-> publicus", "gero -obj-> res"): (
                True
            ),
            ("gero -obj-> res; res -amod-> publicus", "gero -obj-> res; res -(nmod)-> hic"): True,
            # The same schema is no part of itself.
            ("res -amod-> publicus", "res -amod-> publicus"): False,
        }
        for (outer, inner), expected in cases.items():
            with self.subTest(outer=outer, inner=inner):
                self.assertIs(contains(parse_schema(outer), parse_schema(inner)), expected)


class ComponentsTests(PhraseologyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        def unit(form, schema, status=Unit.Status.PROPOSED, user=None):
            return Unit.objects.create(
                reference_form=form, schema=schema, status=status, created_by=user or cls.author
            )

        cls.res_publica = unit("res publica", "res -amod-> publicus", Unit.Status.VALIDATED)
        cls.rem_gerere = unit("rem gerere", "gero -obj|nsubj:pass-> res")
        cls.rem_publicam_gerere = unit(
            "rem publicam gerere", "gero -obj|nsubj:pass-> res; res -amod-> publicus"
        )
        cls.de_re_publica = unit("de re publica bene mereri", DE_RE_PUBLICA)
        cls.bene_mereri = unit("bene mereri", "mereor -advmod-> bene", Unit.Status.DRAFT, cls.other)
        cls.hidden = unit("publica res", "res -amod-> publicus")
        Unit.objects.filter(pk=cls.hidden.pk).update(is_hidden=True)

    def forms(self, found):
        return [component.unit.reference_form for component in found]

    def test_the_components_a_user_may_see(self):
        edges = parse_schema(DE_RE_PUBLICA)
        self.assertEqual(self.forms(components(self.author, edges)), ["res publica"])
        # A draft is seen by its author only.
        self.assertEqual(self.forms(components(self.other, edges)), ["bene mereri", "res publica"])

    def test_the_largest_components_first(self):
        edges = parse_schema("gero -obj-> res; res -amod-> publicus; gero -advmod-> bene")
        self.assertEqual(
            self.forms(components(self.author, edges)),
            ["rem publicam gerere", "rem gerere", "res publica"],
        )

    def test_the_units_that_hold_a_unit(self):
        self.assertEqual(
            self.forms(containers(self.author, self.res_publica)),
            ["de re publica bene mereri", "rem publicam gerere"],
        )
        self.assertEqual(
            self.forms(containers(self.other, self.bene_mereri)), ["de re publica bene mereri"]
        )
        self.assertEqual(self.forms(containers(self.author, self.rem_publicam_gerere)), [])
        self.assertEqual(self.forms(containers(self.author, self.unit)), [])

    def test_components_are_grouped_in_the_schema(self):
        edges = parse_schema(DE_RE_PUBLICA)
        parts, others = schema_parts(edges, components(self.author, edges))
        self.assertEqual([str(part["edge"]) for part in parts[:3]], DE_RE_PUBLICA.split("; ")[:3])
        self.assertEqual(parts[3]["component"].unit, self.res_publica)
        self.assertEqual([str(edge) for edge in parts[3]["edges"]], ["res -amod-> publicus"])
        self.assertEqual(others, [])

    def test_the_page_of_a_unit_shows_its_components(self):
        page = self.client.get(self.de_re_publica.get_absolute_url())
        self.assertContains(page, 'class="schema-component"')
        self.assertContains(page, f'href="{self.res_publica.get_absolute_url()}"')
        # The draft of another account is no component for a visitor.
        self.assertNotContains(page, f'href="{self.bene_mereri.get_absolute_url()}"')
        page = self.client.get(self.res_publica.get_absolute_url())
        self.assertContains(page, "Entre dans")
        self.assertContains(page, f'href="{self.rem_publicam_gerere.get_absolute_url()}"')
        self.assertNotContains(page, "Contient aussi")

    def test_components_while_a_schema_is_drawn(self):
        self.client.force_login(self.other)
        result = self.client.get(
            reverse("phraseology:schema_check"), {"schema": DE_RE_PUBLICA}
        ).json()
        self.assertEqual(
            [component["reference_form"] for component in result["components"]],
            ["bene mereri", "res publica"],
        )
        self.assertEqual(result["components"][1]["lemmas"], ["res", "publicus"])
        self.assertEqual(result["components"][1]["url"], self.res_publica.get_absolute_url())

    def test_the_units_to_insert_in_a_drawing(self):
        url = reverse("phraseology:schema_units")
        units = self.client.get(url, {"fiche": "publica"}).json()["units"]
        self.assertEqual(
            [unit["reference_form"] for unit in units],
            ["de re publica bene mereri", "rem publicam gerere", "res publica"],
        )
        self.assertEqual(
            units[2]["edges"], [{"head": "res", "relations": ["amod"], "dependent": "publicus"}]
        )
        self.assertEqual(
            self.client.get(url, {"fiche": "bene"}).json()["units"][0]["status"], "proposée"
        )
        self.assertEqual(self.client.get(url, {"fiche": " "}).json()["units"], [])

    def test_a_component_sharing_a_relation_is_only_listed(self):
        edges = parse_schema("gero -obj-> res; res -amod-> publicus; gero -advmod-> bene")
        parts, others = schema_parts(edges, components(self.author, edges))
        self.assertEqual(parts[0]["component"].unit, self.rem_publicam_gerere)
        self.assertEqual(len(parts[0]["edges"]), 2)
        self.assertEqual(str(parts[1]["edge"]), "gero -advmod-> bene")
        self.assertEqual(self.forms(others), ["rem gerere", "res publica"])
