from django.urls import reverse

from phraseology.models import Equivalent, Unit, UnitRelation

from .factories import make_unit, set_status
from .test_units import PhraseologyTestCase


class ListAndCreationPagesTests(PhraseologyTestCase):
    def test_the_list_shows_public_units_and_my_drafts(self):
        public = make_unit(self.other, self.more_words[:2], reference_form="consilia capere")
        set_status(public, Unit.Status.PROPOSED)
        url = reverse("phraseology:unit_list")
        response = self.client.get(url)
        self.assertContains(response, "consilia capere")
        self.assertNotContains(response, "consilium capere")
        self.client.force_login(self.author)
        response = self.client.get(url)
        self.assertContains(response, "Mes brouillons")
        self.assertContains(response, "consilium capere")
        self.assertNotContains(self.client.get(url, {"q": "bellum"}), "consilia capere")
        self.assertContains(self.client.get(url, {"q": "consilia"}), "consilia capere")

    def test_creation_from_the_corpus_search(self):
        self.client.force_login(self.other)
        url = reverse("phraseology:unit_create")
        response = self.client.get(url, {"term1": "cepit"})
        self.assertContains(response, f'value="{self.words[1].pk}" form="unit-form"')
        self.assertContains(response, "cochez celles qui attestent l’unité")
        self.assertContains(response, 'name="term5"')
        self.assertContains(response, '<details class="panel-more">')
        four = {"term1": "consilium", "term2": "cepit", "term3": "ut", "term4": "abiret"}
        response = self.client.get(url, four)
        self.assertContains(response, '<details class="panel-more" open>')
        every_word = ",".join(str(word.pk) for word in self.words)
        self.assertContains(response, f'value="{every_word}" form="unit-form"')
        value = f"{self.words[0].pk},{self.words[1].pk}"
        data = {
            "reference_form": " consilium  capere ",
            "definition": "décider",
            "attestation": [value],
        }
        response = self.client.post(url, data)
        unit = Unit.objects.get(created_by=self.other)
        self.assertRedirects(response, unit.get_absolute_url())
        self.assertEqual(unit.reference_form, "consilium capere")
        page = self.client.get(unit.get_absolute_url())
        self.assertContains(page, "<mark")
        self.assertContains(page, "Cic. Off. 1, 1")
        self.assertContains(page, "Brouillon")

    def test_errors_keep_the_ticked_attestations(self):
        self.client.force_login(self.other)
        url = reverse("phraseology:unit_create")
        value = str(self.words[1].pk)
        response = self.client.post(
            url, {"reference_form": "consilium capere", "definition": "", "attestation": [value]}
        )
        self.assertContains(response, f'value="{value}" form="unit-form" checked')
        response = self.client.post(
            url, {"reference_form": "consilium capere", "definition": "décider"}
        )
        self.assertContains(response, "Choisissez au moins une attestation")
        self.assertEqual(Unit.objects.count(), 1)


class UnitPagesTests(PhraseologyTestCase):
    def test_a_draft_is_private(self):
        url = self.unit.get_absolute_url()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("phraseology:unit_edit", args=[self.unit.pk])).status_code, 404
        )
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Modifier la fiche")

    def test_editing_the_unit(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        self.client.force_login(self.other)
        url = reverse("phraseology:unit_edit", args=[self.unit.pk])
        data = {
            "reference_form": "consilium capere",
            "kind": "verb-noun",
            "schema": "Capiō —obj→ cōnsilium",
            "construction": "+ infinitif",
            "register": "standard",
            "usage_marks": ["avoid"],
            "tags": "Décision,  guerre , décision",
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, self.unit.get_absolute_url())
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.schema, "capio -obj-> consilium")
        self.assertEqual(self.unit.tags, ["décision", "guerre"])
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "capio —obj→ consilium")
        self.assertContains(page, "à éviter")
        self.assertContains(page, "Collocation verbe–nom")
        list_page = self.client.get(reverse("phraseology:unit_list"), {"etiquette": "guerre"})
        self.assertContains(list_page, "consilium capere")
        response = self.client.post(url, data | {"schema": "capio obj consilium"})
        self.assertContains(response, "Écrivez chaque relation ainsi")

    def test_adding_changing_and_withdrawing_parts(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        sense = self.unit.senses.get()
        self.client.force_login(self.other)
        url = reverse("phraseology:part_create", args=[self.unit.pk, "equivalents"])
        response = self.client.post(
            url, {"sense": sense.pk, "language": "en", "expression": "make a plan"}
        )
        equivalent = Equivalent.objects.get()
        self.assertRedirects(response, equivalent.get_absolute_url(), fetch_redirect_response=False)
        edit_url = reverse("phraseology:part_edit", args=["equivalents", equivalent.pk])
        self.client.post(
            edit_url, {"sense": sense.pk, "language": "en", "expression": "form a plan"}
        )
        equivalent.refresh_from_db()
        self.assertEqual(equivalent.expression, "form a plan")
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "form a plan")
        self.client.post(reverse("phraseology:part_withdraw", args=["equivalents", equivalent.pk]))
        self.assertNotContains(self.client.get(self.unit.get_absolute_url()), "form a plan")
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        self.assertEqual(
            self.client.get(
                reverse("phraseology:part_create", args=[self.unit.pk, "autre"])
            ).status_code,
            404,
        )

    def test_relations_are_shown_on_both_units(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        target = set_status(
            make_unit(self.other, self.more_words[:2], reference_form="consilium inire"),
            Unit.Status.PROPOSED,
        )
        self.client.force_login(self.author)
        url = reverse("phraseology:part_create", args=[self.unit.pk, "relations"])
        self.client.post(url, {"kind": "broader", "target": target.pk})
        self.assertEqual(UnitRelation.objects.count(), 1)
        self.assertContains(self.client.get(self.unit.get_absolute_url()), "Plus général que")
        self.assertContains(self.client.get(target.get_absolute_url()), "Plus précis que")
        response = self.client.post(url, {"kind": "broader", "target": target.pk})
        self.assertContains(response, "Cette relation est déjà indiquée")

    def test_adding_attestations(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        self.client.force_login(self.other)
        url = reverse("phraseology:attestation_add", args=[self.unit.pk])
        response = self.client.get(url, {"term1": "capiunt"})
        self.assertContains(response, f'value="{self.more_words[1].pk}" form="unit-form"')
        value = f"{self.more_words[0].pk},{self.more_words[1].pk}"
        response = self.client.post(url, {"attestation": [value], "sense": "", "realization": ""})
        self.assertRedirects(
            response, f"{self.unit.get_absolute_url()}#attestations", fetch_redirect_response=False
        )
        self.assertEqual(self.unit.attestations.count(), 2)
        response = self.client.post(url, {"sense": "", "realization": ""})
        self.assertContains(response, "Cochez au moins une attestation")

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        for url in (
            reverse("phraseology:unit_create"),
            reverse("phraseology:unit_edit", args=[self.unit.pk]),
            reverse("phraseology:attestation_add", args=[self.unit.pk]),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
