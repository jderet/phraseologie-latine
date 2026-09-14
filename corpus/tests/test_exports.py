from xml.etree import ElementTree

from django.urls import reverse

from corpus.corrections import propose_correction, review_correction
from corpus.models import AnalysisCorrection
from notebook.services import add_private_note
from phraseology.reading_notes import create_reading_note
from phraseology.services import propose_unit
from phraseology.tests.test_frequency import AnalysedCorpusTestCase


class CorpusExportTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.passage.edition.work
        self.words = list(self.passage.tokens.order_by("position"))

    def fetch(self, kind, **params):
        response = self.client.get(reverse("corpus:export", args=[self.work.cts_id, kind]), params)
        self.assertEqual(response.status_code, 200)
        return response, b"".join(response.streaming_content).decode()

    def test_conllu_of_a_work_with_the_corrected_analysis_and_the_units(self):
        _response, content = self.fetch("conllu")
        self.assertNotIn("Phraseology=", content)
        self.client.force_login(self.author)
        self.assertIn("Phraseology=", self.fetch("conllu")[1])
        self.client.logout()
        propose_unit(self.unit, self.author)
        attestation = self.unit.attestations.get()
        correction = AnalysisCorrection(token=self.words[0], lemma="consilius", reason="Test.")
        propose_correction(correction, self.other)
        review_correction(correction, self.reviewer, AnalysisCorrection.Status.VALIDATED)
        response, content = self.fetch("conllu")
        self.assertIn(f"# newdoc id = {self.passage.edition.cts_urn}", content)
        self.assertIn("# text = Consilium cepit ut abiret.", content)
        self.assertIn(f"Phraseology={self.unit.pk}:{attestation.pk}:proposed", content)
        self.assertIn("\tconsilius\t", content)
        self.assertIn(f"TokenId={self.words[0].pk}|", content)
        rows = [line.split("\t") for line in content.splitlines() if line[:1].isdigit()]
        self.assertTrue(rows)
        self.assertTrue(all(len(row) == 10 for row in rows))
        self.assertIn(f'filename="{self.work.cts_id}.conllu"', response["Content-Disposition"])

    def test_tei_of_a_passage_with_its_units_and_reading_notes(self):
        propose_unit(self.unit, self.author)
        words = ",".join(str(word.pk) for word in self.words[:2])
        create_reading_note(words, self.other, "Tournure & usage.")
        add_private_note(self.other, words, "Note privée secrète.")
        response, content = self.fetch("tei", passage=self.passage.reference)
        ElementTree.fromstring(content.encode())
        self.assertIn(f'<w xml:id="w{self.words[0].pk}"', content)
        self.assertIn('lemma="consilium"', content)
        self.assertIn("Tournure &amp; usage.", content)
        self.assertIn('type="proposed"', content)
        self.assertIn(f'n="{self.passage.reference}"', content)
        self.assertNotIn('n="1.2"', content)
        self.assertNotIn("secrète", content)
        self.assertIn("-1.1.tei.xml", response["Content-Disposition"])

    def test_a_book_and_unknown_requests(self):
        _response, content = self.fetch("tei", passage="1")
        self.assertIn('n="1.3"', content)
        url = reverse("corpus:export", args=[self.work.cts_id, "pdf"])
        self.assertEqual(self.client.get(url).status_code, 404)
        url = reverse("corpus:export", args=[self.work.cts_id, "tei"])
        self.assertEqual(self.client.get(url, {"passage": "9"}).status_code, 404)
