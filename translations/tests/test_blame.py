from django.urls import reverse

from translations.services import create_step, save_translation

from .factories import make_published_version
from .test_versions import TranslationTestCase


class BlameTests(TranslationTestCase):
    def test_each_sentence_with_its_writer(self):
        version = make_published_version(self.author, self.project)
        save_translation(version, self.first, "Pluit multum.", self.author, written_by=self.other)
        create_step(version, self.author, "Phrase réécrite")
        response = self.client.get(reverse("translations:version_blame", args=[version.pk]))
        writers = [row["writer"] for row in response.context["rows"]]
        self.assertEqual(writers, [self.other, self.author, self.author])
        legend = {item["user"]: item["percent"] for item in response.context["legend"]}
        self.assertEqual(legend, {self.other: 33, self.author: 67})

    def test_older_step(self):
        version = make_published_version(self.author, self.project)
        url = reverse("translations:version_blame", args=[version.pk])
        response = self.client.get(url, {"etape": "1"})
        self.assertEqual(response.context["step"].number, 1)
