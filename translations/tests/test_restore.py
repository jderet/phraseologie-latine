from django.urls import reverse

from translations.models import TranslatedSegment
from translations.services import create_step, save_translation

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class RestoreTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version)
        create_step(self.version, self.author, "Premier jet")
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        save_translation(self.version, self.third, "", self.author)
        self.client.force_login(self.author)
        self.url = reverse("translations:step_restore", args=[self.version.pk, 1])

    def text(self, segment):
        return TranslatedSegment.objects.get(version=self.version, segment=segment).text

    def test_preview_then_restore(self):
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["rows"]), 2)
        self.client.post(self.url)
        self.assertEqual(self.text(self.first), "Pluit.")
        self.assertEqual(self.text(self.third), "Cras proficiscemur.")
        self.assertEqual(len(self.client.get(self.url).context["rows"]), 0)

    def test_writers_only(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
