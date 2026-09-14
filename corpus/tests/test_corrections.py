from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from corpus.corrections import current_analysis, propose_correction, review_correction
from corpus.models import AnalysisCorrection, AnalysisLayer, TokenAnalysis
from phraseology.frequency import schema_matches
from phraseology.schema import parse_schema
from phraseology.tests.factories import analyze
from phraseology.tests.test_frequency import AnalysedCorpusTestCase

SCHEMA = "capio -obj|nsubj:pass-> consilium"


class CorrectionTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.cepit = self.words[1]

    def propose(self, **fields):
        correction = AnalysisCorrection(token=self.cepit, reason="L’analyse se trompe.", **fields)
        return propose_correction(correction, self.other)

    def test_a_validated_correction_changes_the_analysis_and_the_search(self):
        correction = self.propose(lemma="concipio")
        self.assertEqual(correction.status, AnalysisCorrection.Status.PROPOSED)
        matches = schema_matches(parse_schema(SCHEMA), self.layer)
        self.assertEqual(matches.count(), 4)
        with self.assertRaises(PermissionDenied):
            review_correction(correction, self.other, AnalysisCorrection.Status.VALIDATED)
        review_correction(correction, self.reviewer, AnalysisCorrection.Status.VALIDATED)
        analysis = current_analysis(self.cepit)
        self.assertEqual(
            (analysis.lemma, analysis.lemma_norm, analysis.origin),
            ("concipio", "concipio", TokenAnalysis.Origin.CORRECTED),
        )
        self.assertEqual(matches.count(), 3)
        with self.assertRaises(ValidationError):
            review_correction(correction, self.reviewer, AnalysisCorrection.Status.REJECTED)

    def test_a_correction_must_change_something(self):
        with self.assertRaises(ValidationError):
            self.propose(lemma="capio")
        elsewhere = TokenAnalysis.objects.filter(token__edition__work__is_core=False).first()
        with self.assertRaises(ValidationError):
            self.propose(head=elsewhere.token)

    def test_validated_corrections_survive_a_new_analysis(self):
        correction = self.propose(lemma="concipio", deprel="conj")
        review_correction(correction, self.reviewer, AnalysisCorrection.Status.VALIDATED)
        rejected = self.propose(upos="NOUN")
        review_correction(rejected, self.reviewer, AnalysisCorrection.Status.REJECTED)
        layer = AnalysisLayer.objects.create(tool="LatinCy test", tool_version="2.0")
        analyze(layer, self.cepit, "capio", upos="VERB")
        layer.make_default()
        analysis = current_analysis(self.cepit, layer=layer)
        self.assertEqual(
            (analysis.lemma, analysis.deprel, analysis.upos), ("concipio", "conj", "VERB")
        )

    def test_proposed_and_reviewed_through_the_pages(self):
        self.client.force_login(self.other)
        url = reverse("corpus:correction_create", args=[self.cepit.pk])
        self.assertContains(self.client.get(url), "capio")
        response = self.client.post(url, {"lemma": "concipio", "reason": "Faute.", "next": "/"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        correction = AnalysisCorrection.objects.get()
        listing = self.client.get(reverse("corpus:corrections"))
        self.assertContains(listing, "concipio")
        self.assertNotContains(listing, 'value="valider"')
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse("corpus:corrections")), 'value="valider"')
        review = reverse("corpus:correction_review", args=[correction.pk])
        self.client.post(review, {"decision": "valider"})
        correction.refresh_from_db()
        self.assertEqual(correction.status, AnalysisCorrection.Status.VALIDATED)
