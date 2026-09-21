from django.urls import reverse

from translations.services import create_step, save_translation

from .factories import make_project, make_published_version, make_version
from .test_versions import TranslationTestCase


class StepLabelTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        create_step(self.version, self.author, "Autre tour")

    def test_label_a_step_and_list_the_editions(self):
        self.client.force_login(self.author)
        url = reverse("translations:step_label", args=[self.version.pk, 1])
        self.client.post(url, {"label": "Édition 1"})
        self.assertEqual(self.version.steps.get(number=1).label, "Édition 1")
        response = self.client.get(self.version.get_absolute_url())
        self.assertContains(response, "Édition 1")

    def test_others_may_not_label(self):
        self.client.force_login(self.other)
        url = reverse("translations:step_label", args=[self.version.pk, 1])
        self.assertEqual(self.client.post(url, {"label": "Pirate"}).status_code, 403)

    def test_export_of_an_older_step(self):
        url = reverse("translations:version_export_text", args=[self.version.pk])
        self.assertIn("Imber cadit.", self.client.get(url).content.decode())
        older = self.client.get(url, {"etape": "1"}).content.decode()
        self.assertIn("Pluit.", older)
        self.assertNotIn("Imber", older)

    def test_export_of_a_hidden_draft_step_is_refused(self):
        draft = make_version(self.author, make_project(self.author, self.source, title="Autre"))
        save_translation(draft, self.first, "Pluit.", self.author)
        create_step(draft, self.author, "Brouillon")
        url = reverse("translations:version_export_text", args=[draft.pk])
        self.assertEqual(self.client.get(url, {"etape": "1"}).status_code, 404)
