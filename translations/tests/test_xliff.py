import xml.etree.ElementTree as ET

from django.urls import reverse

from translations.comments import post_sentence_comment
from translations.services import set_sentence_status

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase

NS = {"x": "urn:oasis:names:tc:xliff:document:1.2"}


class XliffExportTests(TranslationTestCase):
    def units(self, response):
        root = ET.fromstring(response.content)
        return root.findall(".//x:trans-unit", NS)

    def test_working_text_with_statuses_and_notes(self):
        version = make_version(self.author, self.project)
        translate(version, ("Pluit.", "Domi <manemus> & ridemus."))
        set_sentence_status(version, self.first, "reviewed", self.author)
        post_sentence_comment(version, self.second, self.author, "Vérifier « domi ».")
        self.client.force_login(self.author)
        response = self.client.get(reverse("translations:version_export_xliff", args=[version.pk]))
        self.assertEqual(response["Content-Type"], "application/x-xliff+xml; charset=utf-8")
        units = self.units(response)
        self.assertEqual(len(units), 3)
        first, second, third = units
        self.assertEqual(first.get("id"), str(self.first.pk))
        self.assertEqual(first.find("x:target", NS).get("state"), "signed-off")
        self.assertEqual(first.get("approved"), "yes")
        self.assertEqual(second.find("x:target", NS).text, "Domi <manemus> & ridemus.")
        self.assertEqual(second.find("x:note", NS).text, "Vérifier « domi ».")
        self.assertEqual(third.find("x:target", NS).get("state"), "needs-translation")

    def test_the_public_gets_the_public_step(self):
        version = make_published_version(self.author, self.project)
        response = self.client.get(reverse("translations:version_export_xliff", args=[version.pk]))
        target = self.units(response)[0].find("x:target", NS)
        self.assertEqual((target.text, target.get("state")), ("Pluit.", "final"))

    def test_a_draft_is_not_exported_to_others(self):
        version = make_version(self.author, self.project)
        response = self.client.get(reverse("translations:version_export_xliff", args=[version.pk]))
        self.assertEqual(response.status_code, 404)
