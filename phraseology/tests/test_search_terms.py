from django.http import QueryDict
from django.urls import reverse

from corpus.forms import bound_search_form
from corpus.search import build_hits
from phraseology.models import Unit
from phraseology.search_terms import marked_search

from .test_frequency import AnalysedCorpusTestCase

MARKED = "[bonum consilium;bonum consilium] capere"
SCHEMA = "capio -obj-> consilium; consilium -amod-> bonus"


class ConstructionSearchTests(AnalysedCorpusTestCase):
    """Bonum consilium cepit (Cic. Off. 1, 3) holds the construction bonum consilium."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.construction = Unit.objects.create(
            reference_form="bonum consilium",
            schema="consilium -amod-> bonus",
            status=Unit.Status.PROPOSED,
            created_by=cls.author,
        )
        cls.draft = Unit.objects.create(
            reference_form="consilium bonum", schema="consilium -amod-> bonus", created_by=cls.other
        )

    def form(self, user=None, **params):
        data = QueryDict(mutable=True)
        for key, value in params.items():
            data.setlist(key, value if isinstance(value, list) else [value])
        return bound_search_form(data, user=user)

    def test_a_construction_alone_or_with_words(self):
        pk = str(self.construction.pk)
        alone = self.form(construction=pk, term1="", scope="all")
        self.assertTrue(alone.is_valid(), alone.errors)
        self.assertEqual([token.pk for token in alone.hits()], [self.good_words[1].pk])
        near = self.form(construction=pk, term1="capio", mode1="lemma", scope="all")
        self.assertTrue(near.is_valid(), near.errors)
        (hit,) = build_hits(near.hits(), near.terms, layer=self.layer)
        # The words of the construction and the verb; capiunt, in the sentence before, is near too.
        self.assertLessEqual({word.pk for word in self.good_words}, hit.highlighted)
        self.assertIn("bonum consilium (construction)", near.description)
        far = self.form(construction=pk, term1="bellum", scope="all")
        self.assertTrue(far.is_valid(), far.errors)
        self.assertFalse(far.hits().exists())

    def test_a_construction_added_by_its_name(self):
        form = self.form(construction_name="BONVM CONSILIVM", term1="")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["construction"], [self.construction])
        self.assertEqual(form.data.getlist("construction"), [str(self.construction.pk)])
        self.assertEqual(form.data["construction_name"], "")
        unknown = self.form(construction_name="vir bonus", term1="")
        self.assertFalse(unknown.is_valid())
        self.assertIn("construction_name", unknown.errors)

    def test_a_word_or_a_construction_is_needed_and_drafts_stay_private(self):
        empty = self.form(term1="")
        self.assertFalse(empty.is_valid())
        self.assertEqual(empty.errors["term1"], ["Indiquez un mot ou une construction."])
        hidden = self.form(construction=str(self.draft.pk), term1="capio")
        self.assertTrue(hidden.is_valid(), hidden.errors)
        self.assertEqual(hidden.cleaned_data["construction"], [])
        own = self.form(user=self.other, construction=str(self.draft.pk), term1="")
        self.assertTrue(own.is_valid(), own.errors)
        self.assertEqual(own.cleaned_data["construction"], [self.draft])

    def test_the_first_search_of_a_unit(self):
        self.assertEqual(
            marked_search(self.author, MARKED, SCHEMA),
            {"term1": "capio", "construction": [self.construction.pk]},
        )
        self.assertEqual(
            marked_search(self.author, "consilium capere", "capio -obj-> consilium"),
            {"term1": "capio", "term2": "consilium"},
        )

    def test_pages_show_the_constructions(self):
        pk = self.construction.pk
        page = self.client.get(
            reverse("corpus:search"), {"construction": pk, "term1": "", "scope": "all"}
        )
        self.assertContains(page, f'name="construction" value="{pk}" checked')
        self.assertEqual(page.context["page"].paginator.count, 1)
        self.client.force_login(self.author)
        creation = self.client.get(
            reverse("phraseology:unit_create"), {"forme": MARKED, "schema": SCHEMA}
        )
        search = creation.context["search"]["form"]
        self.assertEqual(search.construction_units, [self.construction])
        self.assertEqual(search["term1"].value(), "capio")
        self.assertContains(creation, f'name="construction" value="{pk}" checked')

    def test_the_attestations_of_a_unit_start_from_its_marks(self):
        composed = Unit.objects.create(
            reference_form="bonum consilium capere",
            marked_form=MARKED,
            schema=SCHEMA,
            status=Unit.Status.PROPOSED,
            created_by=self.author,
        )
        self.client.force_login(self.other)
        page = self.client.get(reverse("phraseology:attestation_add", args=[composed.pk]))
        search = page.context["search"]["form"]
        self.assertEqual(search.construction_units, [self.construction])
        self.assertEqual((search["term1"].value(), search["mode1"].value()), ("capio", "lemma"))
