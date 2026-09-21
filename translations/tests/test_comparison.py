from django.urls import reverse

from translations.models import SegmentVariant, Style
from translations.variants import add_variant

from .factories import make_project, make_published_version, make_version
from .test_versions import TranslationTestCase


class ProjectComparisonTests(TranslationTestCase):
    """Two projects translating the same text, aligned sentence by sentence."""

    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        self.other_project = make_project(
            self.other, self.source, title="Pluvia", style=Style.TACITEAN
        )
        self.other_version = make_published_version(
            self.other, self.other_project, texts=("Imber cadit.",)
        )
        self.url = reverse("translations:project_compare", args=[self.project.pk])

    def test_the_translations_of_the_same_text_are_compared(self):
        response = self.client.get(self.url)
        cells = response.context["rows"][0]["cells"]
        self.assertEqual([cell["version"] for cell in cells], [self.version, self.other_version])
        self.assertEqual([cell["text"] for cell in cells], ["Pluit.", "Imber cadit."])
        self.assertContains(response, "Pluvia")

    def test_the_projects_shown_can_be_chosen(self):
        response = self.client.get(self.url, {"p": [self.other_project.pk]})
        cells = response.context["rows"][0]["cells"]
        self.assertEqual([cell["version"] for cell in cells], [self.other_version])

    def test_variants_are_shown_only_when_asked(self):
        add_variant(
            SegmentVariant(
                version=self.version,
                segment=self.first,
                text="Imber ruit.",
                comment="Plus fort.",
            ),
            self.reviewer,
        )
        response = self.client.get(self.url)
        self.assertNotContains(response, "Imber ruit.")
        response = self.client.get(self.url, {"variantes": "1"})
        self.assertContains(response, "Imber ruit.")

    def test_a_draft_of_someone_else_is_never_compared(self):
        hidden = make_project(self.reviewer, self.source, title="Brouillon")
        draft = make_version(self.reviewer, hidden)
        response = self.client.get(self.url)
        self.assertNotIn(draft, response.context["versions"])

    def test_link_from_the_project_page(self):
        response = self.client.get(reverse("translations:project", args=[self.project.pk]))
        self.assertContains(response, self.url)
