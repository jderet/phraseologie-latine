from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from phraseology.collocations import compute_collocations, profile
from phraseology.models import Collocation

from .test_frequency import AnalysedCorpusTestCase


class CollocationTests(AnalysedCorpusTestCase):
    def pair(self, scope, head="capio", relation="obj", dependent="consilium"):
        return Collocation.objects.get(
            scope=scope, head=head, relation=relation, dependent=dependent
        )

    def test_pairs_are_counted_in_three_parts_of_the_corpus(self):
        counts = compute_collocations(self.layer, min_frequency=1)
        self.assertEqual(self.pair("core").frequency, 3)
        self.assertEqual(self.pair("prose").frequency, 4)
        self.assertEqual(self.pair("all").frequency, 4)
        self.assertEqual(self.pair("core").schema, "capio -obj|nsubj:pass-> consilium")
        self.assertIn("LatinCy test 1.0", self.pair("all").corpus_version)
        self.assertEqual(counts["core"], Collocation.objects.filter(scope="core").count())

    def test_verse_is_left_out_of_the_prose(self):
        work = self.seneca.works.get()
        work.form = work.Form.VERSE
        work.save()
        compute_collocations(self.layer, min_frequency=1)
        self.assertEqual(self.pair("prose").frequency, 3)
        self.assertEqual(self.pair("all").frequency, 4)

    def test_a_new_count_replaces_the_previous_one(self):
        first = compute_collocations(self.layer, min_frequency=1)
        self.assertEqual(compute_collocations(self.layer, min_frequency=1), first)
        compute_collocations(self.layer, min_frequency=2)
        self.assertFalse(Collocation.objects.filter(dependent="bonus").exists())

    def test_a_profile_in_both_directions(self):
        compute_collocations(self.layer, min_frequency=1)
        sections = {section["title"]: section for section in profile("consilium", "core")}
        self.assertEqual(
            [row.collocate for row in sections["Verbes dont il est l’objet"]["rows"]], ["capio"]
        )
        self.assertEqual(
            [row.collocate for row in sections["Adjectifs épithètes"]["rows"]], ["bonus"]
        )

    def test_the_command(self):
        output = StringIO()
        call_command("compute_collocations", "--min-frequency=1", stdout=output)
        self.assertIn("noyau :", output.getvalue())
        self.assertIn("Collocations calculées", output.getvalue())


class ProfilePageTests(AnalysedCorpusTestCase):
    def url(self, lemma):
        return reverse("phraseology:collocation_lemma", args=[lemma])

    def test_before_any_count(self):
        page = self.client.get(self.url("capio"))
        self.assertContains(page, "Les profils n’ont pas encore été calculés")

    def test_the_profile_of_a_lemma(self):
        compute_collocations(self.layer, min_frequency=1)
        page = self.client.get(self.url("capio"))
        self.assertContains(page, "Objets (et sujets du passif)")
        self.assertContains(page, self.url("consilium"))
        self.assertContains(
            page, "schema=capio%20-obj%7Cnsubj%3Apass-%3E%20consilium&amp;scope=core"
        )
        self.assertContains(page, "Repéré automatiquement (corpus version")
        page = self.client.get(self.url("capio"), {"portee": "prose"})
        self.assertContains(page, "&amp;scope=all&amp;text_forms=prose")

    def test_a_lemma_typed_in_the_form_and_an_absence(self):
        compute_collocations(self.layer, min_frequency=1)
        response = self.client.get(
            reverse("phraseology:collocation_profile"), {"lemme": " Consilium ", "portee": "all"}
        )
        self.assertRedirects(response, f"{self.url('consilium')}?portee=all")
        page = self.client.get(self.url("nihil"))
        self.assertContains(page, "Aucune collocation de « nihil » dans cette partie du corpus")
        self.assertContains(page, "corpus version")

    def test_the_unit_page_links_to_the_profiles_of_its_lemmas(self):
        self.unit.schema = "capio -obj-> consilium"
        self.unit.save()
        self.client.force_login(self.author)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, self.url("capio"))
        self.assertContains(page, self.url("consilium"))
