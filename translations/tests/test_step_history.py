from django.urls import reverse

from translations.models import TranslationVersion
from translations.services import change_source_text, create_step, publish_version, save_translation

from .factories import make_published_version, make_version, translate
from .test_sources import insert, merge, split
from .test_versions import TranslationTestCase


class StepHistoryTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)

    def fresh_version(self):
        return TranslationVersion.objects.get(pk=self.version.pk)

    def url(self, name, *args):
        return reverse(f"translations:{name}", args=[self.version.pk, *args])

    def test_the_history_sums_up_and_details_what_each_step_changed(self):
        save_translation(self.version, self.second, "Domi maneamus.", self.author)
        create_step(self.version, self.author, "Subjonctif")
        change_source_text(self.source, merge(0), self.author)
        change_source_text(self.source, insert(2, "À bientôt.", "Adieu."), self.author)
        added = self.source.segments.current().get(order=3)
        save_translation(self.fresh_version(), added, "Vale.", self.author)
        create_step(self.fresh_version(), self.author, "Texte source revu")

        page = self.client.get(self.url("step_list"))
        entries = page.context["entries"]
        self.assertEqual([entry["step"].number for entry in entries], [3, 2, 1])
        third, second, first = [entry["comparison"] for entry in entries]
        self.assertEqual((len(first.sentences), first.source_changes), (3, []))
        self.assertEqual(
            [(row["number"], row["before"], row["after"]) for row in second.sentences],
            [(2, "Domi manemus.", "Domi maneamus.")],
        )
        # The merged sentence only followed the source text: its Latin does not count.
        self.assertEqual([(row["number"], row["after"]) for row in third.sentences], [(3, "Vale.")])
        self.assertEqual(
            [item.label for item in third.source_changes],
            ["Phrases 1 et 2 fusionnées", "Phrases 3 à 4 ajoutées"],
        )
        self.assertEqual(third.source_summary, "2 phrases ajoutées, 1 fusion")
        self.assertEqual(third.latin_summary, "1 phrase traduite changée")
        self.assertContains(page, "Voir le détail")
        self.assertContains(page, "texte source : 2 phrases ajoutées, 1 fusion")
        self.assertContains(page, "<del>manemus</del><ins>maneamus</ins>", html=True)

    def test_a_private_draft_step_does_not_show_through_the_public_history(self):
        version = make_version(self.author, self.project)
        translate(version)
        create_step(version, self.author, "Brouillon")
        save_translation(version, self.first, "Imber cadit.", self.author)
        publish_version(version, self.author)
        page = self.client.get(reverse("translations:step_list", args=[version.pk]))
        [entry] = page.context["entries"]
        self.assertEqual(entry["step"].number, 2)
        self.assertEqual(len(entry["comparison"].sentences), 3)
        self.assertNotContains(page, "Pluit.")

    def test_creating_and_comparing_steps_show_the_source_changes(self):
        change_source_text(self.source, split(1, "Nous restons", "à la maison."), self.author)
        self.client.force_login(self.author)
        page = self.client.get(self.url("step_create"))
        self.assertContains(page, "Phrase 2 scindée en 2")
        self.assertEqual(page.context["changes"], [])
        create_step(self.fresh_version(), self.author, "Scission")

        compare = self.client.get(self.url("step_compare"), {"de": 1, "a": 2})
        self.assertContains(compare, "Phrase 2 scindée en 2")
        self.assertEqual(compare.context["rows"], [])
        detail = self.client.get(self.url("step", 2))
        self.assertContains(detail, "Latin inchangé · texte source : 1 scission")
        self.assertContains(detail, "Phrase 2 scindée en 2")
