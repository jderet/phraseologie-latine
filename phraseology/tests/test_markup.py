from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from phraseology.forms import UnitCreateForm, UnitForm
from phraseology.markup import clean_marks, plain_form, resolve, segments, units_named
from phraseology.models import Unit
from phraseology.models import UnitForm as UnitFormRow
from phraseology.schema import parse_schema
from phraseology.tests.factories import make_layer

from .test_units import PhraseologyTestCase

MARKED = "[rēs pūblica;rem pūblicam] administrāre"


class MarksTests(SimpleTestCase):
    def test_the_plain_form_and_the_pieces(self):
        self.assertEqual(plain_form(MARKED), "rem pūblicam administrāre")
        self.assertEqual(plain_form("consilium capere"), "consilium capere")
        parts = segments(MARKED)
        self.assertEqual(
            [(part.text, part.name) for part in parts],
            [("rem pūblicam", "rēs pūblica"), (" administrāre", "")],
        )

    def test_marks_are_written_again_with_single_spaces(self):
        self.assertEqual(
            clean_marks("[ rēs  pūblica ; rem pūblicam ] x"), "[rēs pūblica;rem pūblicam] x"
        )

    def test_invalid_marks(self):
        cases = {
            "[rēs pūblica rem pūblicam] administrāre": "mark",
            "[rēs pūblica;rem pūblicam administrāre": "mark",
            "rem pūblicam] administrāre": "mark",
            "[;rem pūblicam] administrāre": "mark_empty",
            " ".join(["[a;b]"] * 6): "too_many_marks",
        }
        for text, code in cases.items():
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                clean_marks(text)
            self.assertEqual(caught.exception.code, code)


class ResolveTests(PhraseologyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        def unit(form, schema, status, user=None):
            return Unit.objects.create(
                reference_form=form, schema=schema, status=status, created_by=user or cls.author
            )

        cls.validated = unit("res publica", "res -nmod-> publicus", Unit.Status.VALIDATED)
        cls.within = unit("rēs pūblica", "res -amod-> publicus", Unit.Status.PROPOSED)
        cls.draft = unit("Res Publica", "res -amod-> publicus", Unit.Status.DRAFT, cls.other)
        cls.composed = Unit.objects.create(
            reference_form="rem pūblicam administrāre",
            marked_form=MARKED,
            schema="administro -obj-> res; res -amod-> publicus",
            status=Unit.Status.PROPOSED,
            created_by=cls.author,
        )

    def test_a_name_whatever_its_macrons_and_case(self):
        self.assertEqual(
            {unit.pk for unit in units_named(self.author, "RĒS PVBLICA")},
            {self.validated.pk, self.within.pk},
        )
        self.assertEqual(len(units_named(self.other, "res publica")), 3)
        self.assertEqual(units_named(self.author, "res"), [])

    def test_the_unit_within_the_schema_comes_first(self):
        (mark, rest) = resolve(self.author, MARKED, self.composed.edges)
        self.assertEqual((mark.unit, mark.others), (self.within, [self.validated]))
        self.assertIsNone(rest.unit)
        # Without a schema, the validated unit comes first.
        (mark, _rest) = resolve(self.author, MARKED)
        self.assertEqual((mark.unit, mark.others), (self.validated, [self.within]))
        (mark,) = resolve(self.author, "[vir bonus;uiri boni]")
        self.assertEqual((mark.unit, mark.others), (None, []))

    def test_the_form_keeps_both_forms(self):
        form = UnitCreateForm(
            {
                "reference_form": "[rēs pūblica ;rem pūblicam]  administrāre",
                "schema": "administro -obj-> res",
                "definition": "gouverner l’État",
            },
            user=self.author,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["reference_form"], "rem pūblicam administrāre")
        self.assertEqual(form.instance.marked_form, MARKED)
        plain = UnitCreateForm(
            {"reference_form": "consilium capere", "schema": "", "definition": "décider"},
            user=self.author,
        )
        self.assertTrue(plain.is_valid(), plain.errors)
        self.assertEqual(plain.instance.marked_form, "")
        wrong = UnitCreateForm(
            {"reference_form": "[rēs pūblica] administrāre", "schema": "", "definition": "x"},
            user=self.author,
        )
        self.assertIn("reference_form", wrong.errors)
        self.assertEqual(
            UnitForm(instance=self.composed, user=self.author)["reference_form"].value(), MARKED
        )

    def test_pages_show_the_marked_words_and_their_bubble(self):
        page = self.client.get(self.composed.get_absolute_url())
        self.assertContains(page, '<mark class="form-mark-words">rem pūblicam</mark>', count=1)
        self.assertContains(page, f'href="{self.within.get_absolute_url()}"')
        self.assertContains(page, f'href="{self.validated.get_absolute_url()}"')
        # A draft of another account is named to no one else.
        self.assertNotContains(page, f'href="{self.draft.get_absolute_url()}"')
        listing = self.client.get(reverse("phraseology:unit_list"))
        self.assertContains(listing, 'class="marked-form"')
        self.assertContains(listing, "rem pūblicam</mark> administrāre</a>")

    def test_the_schema_of_the_composed_unit_is_read(self):
        self.assertEqual(len(parse_schema(self.composed.schema)), 2)


class FormHelpTests(PhraseologyTestCase):
    """What the drawing shows under a reference form being written."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.res_publica = Unit.objects.create(
            reference_form="rēs pūblica",
            schema="res -amod-> publicus",
            status=Unit.Status.VALIDATED,
            created_by=cls.author,
        )
        UnitFormRow.objects.bulk_create(
            [
                UnitFormRow(unit=cls.res_publica, lemma="res", norm="rem"),
                UnitFormRow(unit=cls.res_publica, lemma="publicus", norm="publicam"),
            ]
        )

    def help(self, text, schema=""):
        url = reverse("phraseology:schema_form")
        return self.client.get(url, {"forme": text, "schema": schema}).json()

    def test_a_known_unit_in_the_words_is_suggested(self):
        data = self.help("rem pūblicam administrāre")
        (suggestion,) = data["suggestions"]
        self.assertEqual(
            (suggestion["reference_form"], suggestion["excerpt"], suggestion["status"]),
            ("rēs pūblica", "rem pūblicam", "validée"),
        )
        self.assertEqual(
            suggestion["edges"],
            [{"head": "res", "relations": ["amod"], "dependent": "publicus", "optional": False}],
        )
        self.assertEqual([part["name"] for part in data["parts"]], [""])

    def test_a_marked_unit_is_named_and_no_longer_suggested(self):
        data = self.help(
            "[res publica;rem pūblicam] administrāre", "administro -obj-> res; res -amod-> publicus"
        )
        self.assertEqual(data["suggestions"], [])
        mark = data["parts"][0]
        self.assertEqual(mark["text"], "rem pūblicam")
        self.assertEqual(mark["unit"]["url"], self.res_publica.get_absolute_url())
        self.assertEqual(len(mark["unit"]["edges"]), 1)

    def test_the_unit_itself_and_badly_written_marks(self):
        self.assertEqual(self.help("rem pūblicam")["suggestions"], [])
        self.assertTrue(self.help("[rēs pūblica rem] administrāre")["errors"])

    def test_units_to_build_on_whatever_their_macrons(self):
        url = reverse("phraseology:schema_units")
        units = self.client.get(url, {"fiche": "RES PVBLICA"}).json()["units"]
        self.assertEqual([unit["reference_form"] for unit in units], ["rēs pūblica"])


class CreationPageTests(PhraseologyTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.layer = make_layer()

    def test_the_search_follows_the_schema_and_looks_for_its_lemmas(self):
        self.client.force_login(self.author)
        page = self.client.get(
            reverse("phraseology:unit_create"),
            {
                "forme": MARKED,
                "schema": "administro -obj-> res; res -amod-> publicus",
                "sens": "gouverner l’État",
            },
        )
        html = page.content.decode()
        self.assertLess(html.index('name="schema"'), html.index('id="attestation-search"'))
        self.assertLess(html.index('id="attestation-search"'), html.index('name="definition"'))
        # Words outside the marks; administrāre, unknown here, is looked for as written.
        search = page.context["search"]["form"]
        self.assertEqual(
            [search["term1"].value(), search["term2"].value(), search["mode1"].value()],
            ["administrāre", None, "form"],
        )
        self.assertContains(page, f'value="{MARKED}"')
        self.assertContains(page, "gouverner l’État</textarea>")
        self.assertContains(page, '<button type="submit" class="button" form="unit-form">')

    def test_without_schema_the_search_is_empty_but_looks_for_lemmas(self):
        self.client.force_login(self.author)
        search = self.client.get(reverse("phraseology:unit_create")).context["search"]["form"]
        self.assertEqual((search["term1"].value(), search["mode2"].value()), (None, "lemma"))
