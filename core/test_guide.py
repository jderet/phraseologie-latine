from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.roles import ADMINISTRATOR, REVIEWER
from accounts.tests.factories import make_user
from core.guide import publish_guide, render_guide
from core.models import GuideVersion


class GuideTextTests(SimpleTestCase):
    def test_headings_lists_and_paragraphs_with_the_text_escaped(self):
        text = (
            "## Formules\nUne formule <b>figée</b>\nsur deux lignes.\n\n"
            "- quam ob rem\n- ut ita dicam\n### Clausules\nfin"
        )
        self.assertHTMLEqual(
            render_guide(text),
            '<h2 id="formules">Formules</h2>'
            "<p>Une formule &lt;b&gt;figée&lt;/b&gt; sur deux lignes.</p>"
            "<ul><li>quam ob rem</li><li>ut ita dicam</li></ul>"
            '<h3 id="clausules">Clausules</h3><p>fin</p>',
        )


class GuidePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.administrator = make_user(
            email="admin@example.org", display_name="Porteur", role=ADMINISTRATOR
        )
        cls.reviewer = make_user(email="reviewer@example.org", display_name="Titus", role=REVIEWER)

    def test_before_any_version_the_provisional_typology(self):
        response = self.client.get(reverse("core:guide"))
        self.assertContains(response, "pas encore publié")
        self.assertContains(response, "Collocation verbe–nom")
        self.assertNotContains(response, "Publier une nouvelle version")

    def test_an_administrator_publishes_dated_versions(self):
        with self.assertRaises(PermissionDenied):
            publish_guide("texte", "", self.reviewer)
        self.client.force_login(self.administrator)
        url = reverse("core:guide_publish")
        response = self.client.post(url, {"text": "## Types\nPremière version.", "summary": "v0"})
        first = GuideVersion.objects.get()
        self.assertRedirects(response, first.get_absolute_url())
        self.assertEqual(first.number, 1)
        self.assertContains(self.client.get(url), "Première version.")
        self.client.post(url, {"text": "## Types\nDeuxième version.", "summary": ""})
        page = self.client.get(reverse("core:guide"))
        self.assertContains(page, "Deuxième version.")
        self.assertContains(page, "Version 2, publiée le")
        earlier = self.client.get(first.get_absolute_url())
        self.assertContains(earlier, "Première version.")
        self.assertContains(earlier, "Une version plus récente existe")

    def test_only_administrators_publish(self):
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse("core:guide_publish")).status_code, 403)
