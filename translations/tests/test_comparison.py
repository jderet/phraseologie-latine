from django.urls import reverse

from moderation.models import Revision
from moderation.services import hide_content, revert_to
from translations.models import Style, TranslationVersion
from translations.services import set_aside_variant

from .factories import make_project, make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class MainVersionTests(TranslationTestCase):
    """A project aims at one translation, its main version, in the style of the project."""

    def test_a_project_is_created_with_its_main_version(self):
        main = self.project.main_version
        self.assertTrue(main.is_main)
        self.assertTrue(main.is_draft)
        self.assertEqual((main.author, main.project), (self.author, self.project))
        self.assertEqual(self.project.style, Style.CICERONIAN)
        self.assertEqual(main.display_name, "Traduction principale")

    def test_other_versions_are_open_variants(self):
        variant = make_version(self.other, self.project)
        self.assertTrue(variant.is_open_variant)
        self.assertEqual(variant.display_name, "Variante de Quintus")
        self.assertEqual(str(variant), "La pluie en latin, variante de Quintus")

    def test_several_projects_on_one_text(self):
        tacitus = make_project(self.other, self.source, title="Pluvia", style=Style.TACITEAN)
        self.assertEqual(tacitus.main_version.author, self.other)
        self.assertEqual(self.source.projects.count(), 2)

    def test_a_revert_keeps_the_main_version(self):
        creation = Revision.objects.for_object(self.project).get()
        main = self.project.main_version
        self.project.title = "Titre changé"
        self.project.save()
        revert_to(creation, self.reviewer)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "La pluie en latin")
        self.assertEqual(self.project.main_version, main)


class ComparisonTests(TranslationTestCase):
    def setUp(self):
        self.main = make_published_version(
            self.author, self.project, texts=("Pluit.", "Domi manemus.")
        )
        self.variant = make_published_version(self.other, self.project, texts=("Imber.",))
        self.draft = make_version(self.reviewer, self.project)
        translate(self.draft, ("Pluvia cadit.",))
        self.url = reverse("translations:project_compare", args=[self.project.pk])

    def test_main_version_first_then_the_variants(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.main, self.variant])
        rows = response.context["rows"]
        self.assertEqual([cell["text"] for cell in rows[0]["cells"]], ["Pluit.", "Imber."])
        self.assertEqual([cell["text"] for cell in rows[1]["cells"]], ["Domi manemus.", ""])
        self.assertContains(response, "Nous restons à la maison.")
        self.assertContains(response, 'class="is-reference"')
        self.assertNotContains(response, "Pluvia cadit.")

    def test_closed_variants_come_last(self):
        later = make_published_version(self.reviewer, self.project, texts=("Nimbus.",))
        set_aside_variant(self.variant, self.author, "Hors du style cicéronien.")
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.main, later, self.variant])
        self.assertContains(response, "variante écartée")

    def test_the_author_also_sees_their_draft(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.main, self.variant, self.draft])
        self.assertContains(response, "Pluvia cadit.")
        self.assertContains(response, "votre brouillon")

    def test_versions_can_be_chosen(self):
        response = self.client.get(self.url, {"v": [self.variant.pk, "x", self.draft.pk]})
        self.assertEqual(response.context["shown"], [self.variant])
        self.assertEqual(len(response.context["versions"]), 2)

    def test_hidden_versions_are_not_compared(self):
        hide_content(self.variant, self.reviewer)
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.main])
        self.assertFalse(
            TranslationVersion.objects.get(pk=self.variant.pk).is_closed,
            "hiding a variant does not close it",
        )

    def test_link_from_the_project_page(self):
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, self.url)
