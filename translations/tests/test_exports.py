import xml.etree.ElementTree as ET

from django.urls import reverse

from justifications.services import reference_evidence
from justifications.tests.test_services import JustificationTestCase
from moderation.services import hide_content
from translations.services import publish_version


class ExportTests(JustificationTestCase):
    def setUp(self):
        super().setUp()
        evidences = [self.attestation(), reference_evidence(self.grammar, "§ 426")]
        self.justification = self.justify(comment="Tour cicéronien.", evidences=evidences)
        self.text_url = reverse("translations:version_export_text", args=[self.version.pk])
        self.print_url = reverse("translations:version_export_print", args=[self.version.pk])
        self.tei_url = reverse("translations:version_export_tei", args=[self.version.pk])
        self.tmx_url = reverse("translations:version_export_tmx", args=[self.version.pk])

    def test_bilingual_text(self):
        self.client.force_login(self.author)
        response = self.client.get(self.text_url)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"], 'attachment; filename="la-pluie-en-latin-marcus.txt"'
        )
        text = response.content.decode()
        self.assertIn("2. Nous restons à la maison.\n   Domi manemus.", text)
        self.assertIn("Traduction latine sous licence CC BY-SA 4.0.", text)
        self.assertIn("Brouillon non publié.", text)

    def test_printable_page_with_notes(self):
        self.client.force_login(self.author)
        response = self.client.get(self.print_url)
        self.assertContains(response, 'href="#note-1"')
        self.assertContains(response, 'id="note-1"')
        self.assertContains(response, "Tour cicéronien.")
        self.assertContains(response, "Cic. Off. 1, 1")
        self.assertContains(response, "A&amp;G § 426")
        self.assertContains(response, "Citations du corpus : Perseus, CC BY-SA 4.0.")
        self.assertContains(response, "Enregistrer au format PDF")

    def test_tei_document(self):
        self.client.force_login(self.author)
        response = self.client.get(self.tei_url)
        self.assertEqual(response["Content-Type"], "application/tei+xml; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="la-pluie-en-latin-marcus.tei.xml"',
        )
        root = ET.fromstring(response.content)
        tei = {"tei": "http://www.tei-c.org/ns/1.0"}
        latin = {
            ab.get("corresp"): ab.text
            for ab in root.findall(".//tei:div[@type='translation']/tei:ab", tei)
        }
        self.assertEqual(latin["#source-2"], "Domi manemus.")
        source = root.find(".//tei:div[@type='source']/tei:ab[@n='2']", tei)
        self.assertEqual(source.text, "Nous restons à la maison.")
        note = root.find(".//tei:note[@type='justification']", tei)
        self.assertEqual(note.find("tei:p", tei).text, "Tour cicéronien.")
        references = [ref.text for ref in note.findall("tei:ref", tei)]
        self.assertIn("Cic. Off. 1, 1", references)
        self.assertIn("A&G § 426", references)
        licence = root.find(".//tei:licence", tei)
        self.assertEqual(licence.text, "CC BY-SA 4.0")

    def test_tmx_translation_memory(self):
        self.client.force_login(self.author)
        response = self.client.get(self.tmx_url)
        self.assertEqual(response["Content-Type"], "application/x-tmx+xml; charset=utf-8")
        root = ET.fromstring(response.content)
        self.assertEqual(root.find("header").get("srclang"), "fr")
        lang = "{http://www.w3.org/XML/1998/namespace}lang"
        unit = root.find("body/tu[@tuid='2']")
        segments = {tuv.get(lang): tuv.find("seg").text for tuv in unit.findall("tuv")}
        self.assertEqual(segments, {"fr": "Nous restons à la maison.", "la": "Domi manemus."})

    def test_drafts_are_exported_for_their_author_only(self):
        for user in (None, self.other, self.reviewer):
            if user:
                self.client.force_login(user)
            for url in (self.text_url, self.print_url, self.tei_url, self.tmx_url):
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)
        publish_version(self.version, self.author)
        self.client.logout()
        self.assertNotIn("Brouillon", self.client.get(self.text_url).content.decode())
        self.assertContains(self.client.get(self.print_url), "Tour cicéronien.")

    def test_hidden_justifications_are_left_out(self):
        publish_version(self.version, self.author)
        hide_content(self.justification, self.reviewer)
        self.assertNotContains(self.client.get(self.print_url), "Tour cicéronien.")
        self.assertNotIn("Tour cicéronien.", self.client.get(self.tei_url).content.decode())

    def test_links_from_the_version_page(self):
        self.client.force_login(self.author)
        response = self.client.get(self.version.get_absolute_url())
        self.assertContains(response, self.text_url)
        self.assertContains(response, self.print_url)
        self.assertContains(response, self.tei_url)
        self.assertContains(response, self.tmx_url)
