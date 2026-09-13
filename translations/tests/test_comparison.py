from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from moderation.models import Revision
from moderation.services import hide_content, revert_to
from translations.models import Style
from translations.services import set_reference_version

from .factories import make_project, make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class ReferenceVersionTests(TranslationTestCase):
    def setUp(self):
        self.published = make_published_version(self.other, self.project)
        self.draft = make_version(self.other, self.project, style=Style.TACITEAN)
        self.url = reverse("translations:project_reference", args=[self.project.pk])

    def test_the_creator_chooses_a_published_version(self):
        self.client.force_login(self.author)
        response = self.client.post(self.url, {"version": self.published.pk})
        self.assertRedirects(response, self.project.get_absolute_url())
        self.project.refresh_from_db()
        self.assertEqual(self.project.reference_version, self.published)
        page = self.client.get(self.project.get_absolute_url())
        self.assertContains(page, 'class="badge reference-badge"')
        self.assertContains(page, "Retirer le statut de référence")
        version_page = self.client.get(self.published.get_absolute_url())
        self.assertContains(version_page, 'class="badge reference-badge"')

        self.client.post(self.url, {"version": ""})
        self.project.refresh_from_db()
        self.assertIsNone(self.project.reference_version)
        self.assertEqual(Revision.objects.for_object(self.project).count(), 3)

    def test_only_a_published_version_of_the_project(self):
        other_project = make_project(self.author, self.source, title="Autre projet")
        elsewhere = make_published_version(self.other, other_project)
        self.client.force_login(self.author)
        for version in (self.draft, elsewhere):
            with self.subTest(version=version.pk):
                response = self.client.post(self.url, {"version": version.pk}, follow=True)
                self.assertContains(response, "Choisissez une version publiée de ce projet.")
        self.project.refresh_from_db()
        self.assertIsNone(self.project.reference_version)
        with self.assertRaises(ValidationError):
            set_reference_version(self.project, self.draft, self.author)

    def test_no_one_else_chooses(self):
        for user in (self.other, self.reviewer):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.post(self.url, {"version": self.published.pk})
                self.assertEqual(response.status_code, 403)
        with self.assertRaises(PermissionDenied):
            set_reference_version(self.project, self.published, self.reviewer)
        self.client.force_login(self.other)
        self.assertNotContains(
            self.client.get(self.project.get_absolute_url()), "Choisir comme version de référence"
        )

    def test_a_revert_keeps_the_reference(self):
        creation = Revision.objects.for_object(self.project).get()
        self.project.title = "Titre changé"
        self.project.save()
        set_reference_version(self.project, self.published, self.author)
        revert_to(creation, self.reviewer)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, "La pluie en latin")
        self.assertEqual(self.project.reference_version, self.published)


class ComparisonTests(TranslationTestCase):
    def setUp(self):
        self.cicero = make_published_version(
            self.other, self.project, texts=("Pluit.", "Domi manemus.")
        )
        self.tacitus = make_published_version(
            self.reviewer, self.project, style=Style.TACITEAN, texts=("Imber.",)
        )
        self.draft = make_version(self.author, self.project, style=Style.LIVIAN)
        translate(self.draft, ("Pluvia cadit.",))
        set_reference_version(self.project, self.tacitus, self.author)
        self.url = reverse("translations:project_compare", args=[self.project.pk])

    def test_published_versions_sentence_by_sentence_reference_first(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.tacitus, self.cicero])
        rows = response.context["rows"]
        self.assertEqual([cell["text"] for cell in rows[0]["cells"]], ["Imber.", "Pluit."])
        self.assertEqual([cell["text"] for cell in rows[1]["cells"]], ["", "Domi manemus."])
        self.assertContains(response, "Nous restons à la maison.")
        self.assertContains(response, 'class="is-reference"')
        self.assertNotContains(response, "Pluvia cadit.")

    def test_the_author_also_sees_their_draft(self):
        self.client.force_login(self.author)
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.tacitus, self.cicero, self.draft])
        self.assertContains(response, "Pluvia cadit.")
        self.assertContains(response, "votre brouillon")

    def test_versions_can_be_chosen(self):
        response = self.client.get(self.url, {"v": [self.cicero.pk, "x", self.draft.pk]})
        self.assertEqual(response.context["shown"], [self.cicero])
        self.assertEqual(len(response.context["versions"]), 2)

    def test_hidden_versions_are_not_compared(self):
        hide_content(self.cicero, self.reviewer)
        response = self.client.get(self.url)
        self.assertEqual(response.context["shown"], [self.tacitus])

    def test_link_from_the_project_page(self):
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, self.url)
