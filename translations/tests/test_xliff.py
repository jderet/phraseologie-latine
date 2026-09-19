import xml.etree.ElementTree as ET

from django.urls import reverse

from translations.comments import post_sentence_comment
from translations.models import TranslatedSegment
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


class XliffImportTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version, ("Pluit.",))
        self.client.force_login(self.author)
        self.url = reverse("translations:xliff_import", args=[self.version.pk])

    def exported(self):
        url = reverse("translations:version_export_xliff", args=[self.version.pk])
        return self.client.get(url).content.decode()

    def upload(self, content, name="version.xlf"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        data = content if isinstance(content, bytes) else content.encode()
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, data)})

    def test_round_trip_through_translation_software(self):
        content = self.exported()
        content = content.replace(
            '<target xml:lang="la" state="needs-translation"></target>',
            '<target xml:lang="la" state="signed-off">Domi manemus.</target>',
            1,
        )
        response = self.upload(content)
        self.assertEqual([row["number"] for row in response.context["rows"]], [2])
        self.client.post(
            self.url, {"action": "appliquer", "phrase": [self.second.pk], "statuts": "1"}
        )
        translated = TranslatedSegment.objects.get(version=self.version, segment=self.second)
        self.assertEqual((translated.text, translated.status), ("Domi manemus.", "reviewed"))

    def test_a_document_type_is_refused(self):
        response = self.upload(
            '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><xliff>&a;</xliff>'
        )
        self.assertContains(response, "déclare un type de document")
        self.assertFalse(response.context["rows"])

    def test_utf16_is_refused(self):
        response = self.upload('<?xml version="1.0" encoding="UTF-16"?><xliff/>'.encode("utf-16"))
        self.assertContains(response, "encodé en UTF-8")

    def test_not_xliff(self):
        response = self.upload("<tmx/>")
        self.assertContains(response, "n’est pas un fichier XLIFF")

    def test_units_of_another_text_are_ignored(self):
        response = self.upload(
            '<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2"><file><body>'
            '<trans-unit id="999999"><source>x</source><target>y</target></trans-unit>'
            "</body></file></xliff>"
        )
        self.assertEqual(response.context["unknown"], 1)

    def test_writers_only(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
