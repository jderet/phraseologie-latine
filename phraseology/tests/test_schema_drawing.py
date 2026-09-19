from django.urls import reverse

from .test_units import PhraseologyTestCase

RELATION_OPTION = (
    '<option value="nsubj:pass" data-short="sujet d’un passif">'
    "sujet d’un passif (nsubj:pass)</option>"
)


class SchemaDrawingPagesTests(PhraseologyTestCase):
    def assertDraws(self, page):
        self.assertContains(page, "js/schema.js")
        self.assertContains(page, 'class="schema-builder" hidden')
        self.assertContains(page, 'data-input="id_schema"')
        self.assertContains(page, 'data-words-from="reference_form"')
        self.assertContains(page, 'data-count="1"')
        self.assertContains(page, f'data-lemmas-url="{reverse("phraseology:schema_lemmas")}"')
        self.assertContains(page, f'data-check-url="{reverse("phraseology:schema_check")}"')
        self.assertContains(page, 'data-label-lemma-of="Lemme de « %s »"')
        self.assertContains(page, RELATION_OPTION)
        self.assertNotContains(page, 'value="root"')
        self.assertContains(page, 'class="schema-optional-box"')
        self.assertContains(page, 'data-label-optional="facultatif"')

    def test_the_creation_page_draws_the_schema(self):
        self.client.force_login(self.other)
        page = self.client.get(
            reverse("phraseology:unit_create"),
            {"forme": "consilium capere", "schema": "capio -obj-> consilium"},
        )
        self.assertDraws(page)
        # Without script, the schema is still written in its field.
        self.assertContains(page, 'name="schema" value="capio -obj-&gt; consilium"')

    def test_the_edit_page_draws_the_schema(self):
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        self.unit.save()
        self.client.force_login(self.author)
        page = self.client.get(reverse("phraseology:unit_edit", args=[self.unit.pk]))
        self.assertDraws(page)
        self.assertContains(page, 'value="capio -obj|nsubj:pass-&gt; consilium"')

    def test_an_optional_relation_written_without_script(self):
        self.unit.schema = "capio -obj-> consilium; consilium -(amod)-> bonus"
        self.unit.save()
        self.client.force_login(self.author)
        page = self.client.get(reverse("phraseology:unit_edit", args=[self.unit.pk]))
        self.assertContains(page, 'value="capio -obj-&gt; consilium; consilium -(amod)-&gt; bonus"')
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "consilium —(amod)→ bonus")
        self.assertContains(page, '<span class="schema-edge-optional" lang="fr">facultatif</span>')

    def test_the_schema_search_draws_with_an_open_slot(self):
        page = self.client.get(reverse("phraseology:schema_search"), {"schema": "capio -obj-> *"})
        self.assertContains(page, "js/schema.js")
        self.assertContains(page, 'class="schema-builder" hidden')
        self.assertContains(page, 'data-words-from=""')
        self.assertContains(page, 'data-slot="1"')
        self.assertContains(page, 'data-count=""')
        self.assertContains(page, "Ajouter « n’importe quel mot »")
        self.assertContains(page, 'name="schema" value="capio -obj-&gt; *"')
        # The list of relations is for pages read without script.
        self.assertContains(page, "<noscript>")

    def test_the_drawing_is_translated(self):
        self.client.force_login(self.other)
        page = self.client.get(
            reverse("phraseology:unit_create"), headers={"accept-language": "en"}
        )
        self.assertContains(page, "has as")
        self.assertContains(page, 'data-label-lemma-of="Lemma of “%s”"')
        self.assertContains(page, "passive subject (nsubj:pass)")
