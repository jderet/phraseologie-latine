from unittest import mock

from django.urls import reverse

from corpus.corrections import propose_correction, review_correction
from corpus.models import AnalysisCorrection
from moderation.services import hide_content
from notebook.services import add_private_note
from phraseology.models import NegativeSearch, Unit
from phraseology.reading_notes import create_reading_note
from phraseology.services import propose_unit
from phraseology.sightings import create_sighting
from phraseology.tests.factories import OWNER, make_abstract_word, make_unit
from phraseology.tests.test_neologisms import NeologismTestCase
from translations.tests.factories import (
    make_project,
    make_published_version,
    make_version,
    translate,
)


class ApiTestCase(NeologismTestCase):
    """A proposed unit and a draft, a neologism, a published version and a draft version."""

    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        self.draft = make_unit(self.author, self.more_words[:2], reference_form="consilia capere")
        project = make_project(self.author)
        self.version = make_published_version(self.author, project)
        draft_project = make_project(self.other, project.source_text, title="Brouillon")
        self.draft_version = make_version(self.other, draft_project)
        translate(self.draft_version, ("Pluit secretum.",))
        NegativeSearch.objects.create(
            expression="birota",
            query="term1=birota",
            corpus_version="Perseus test",
            created_by=self.author,
        )

    def get(self, name, *args, **params):
        response = self.client.get(reverse(f"api:{name}", args=args), params)
        return response, response.json()


class ApiTests(ApiTestCase):
    def test_the_entry_point(self):
        response, data = self.get("index")
        self.assertEqual(data["license"], "CC BY-SA 4.0")
        self.assertEqual(
            set(data["endpoints"]),
            {
                "units",
                "neologisms",
                "abstract_words",
                "versions",
                "negative_searches",
                "sightings",
                "reading_notes",
                "corrections",
                "topics",
                "glossaries",
            },
        )
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_abstract_words(self):
        word = make_abstract_word(self.author, rules=OWNER, name="possesseur")
        hidden = make_abstract_word(self.author, name="occultum")
        hide_content(hidden, self.reviewer)
        _response, data = self.get("abstract_words")
        self.assertEqual([result["name"] for result in data["results"]], ["possesseur"])
        _response, found = self.get("abstract_word", word.pk)
        self.assertEqual(found["rules"][0]["feats"], ["Case=Gen"])
        self.assertEqual(found["rules"][0]["label"], "nom commun, nom propre ou pronom, génitif")
        Unit.objects.filter(pk=self.unit.pk).update(
            schema="capio -obj-> consilium; consilium -(nmod)-> {possesseur}"
        )
        _response, unit = self.get("unit", self.unit.pk)
        self.assertEqual(unit["abstract_words"], ["possesseur"])

    def test_units_without_drafts(self):
        _response, data = self.get("units")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["reference_form"], "consilium capere")
        response, _data = self.get("unit", self.draft.pk)
        self.assertEqual(response.status_code, 404)
        _response, unit = self.get("unit", self.unit.pk)
        self.assertEqual(unit["status"], "proposed")
        self.assertEqual(unit["senses"][0]["definition"], "prendre une décision")
        (attestation,) = unit["attestations"]
        self.assertEqual(attestation["word_ids"], [word.pk for word in self.words[:2]])
        self.assertTrue(attestation["urn"].endswith(":1.1"))
        self.assertEqual(attestation["level"], "validated")

    def test_hidden_content_is_left_out(self):
        hide_content(self.unit, self.reviewer)
        self.assertEqual(self.get("units")[1]["count"], 0)
        self.assertEqual(self.get("unit", self.unit.pk)[0].status_code, 404)

    def test_published_versions_only_even_for_their_author(self):
        self.client.force_login(self.other)
        _response, data = self.get("versions")
        self.assertEqual([item["id"] for item in data["results"]], [self.version.pk])
        self.assertEqual(self.get("version", self.draft_version.pk)[0].status_code, 404)
        response, version = self.get("version", self.version.pk)
        self.assertEqual(version["segments"][1]["latin"], "Domi manemus.")
        self.assertEqual(version["author"], "Marcus")
        self.assertEqual(version["source_text"]["genres"], ["article-presse"])
        self.assertEqual(version["source_text"]["themes"], [])
        self.assertNotIn("Pluit secretum", response.content.decode())
        self.assertNotIn("@example.org", response.content.decode())

    def test_neologisms_and_their_evidence(self):
        _response, data = self.get("neologisms")
        self.assertEqual(data["results"][0]["form"], "birota")
        _response, neologism = self.get("neologism", self.neologism.pk)
        corpus, reference = neologism["evidences"]
        self.assertEqual(corpus["corpus"]["citation"], "Cic. Off. 1, 1")
        self.assertEqual(reference["reference"]["work"], "A&G")

    def test_negative_searches(self):
        _response, data = self.get("negative_searches")
        self.assertEqual(data["results"][0]["expression"], "birota")
        self.assertTrue(data["results"][0]["search_url"].endswith("/recherche/?term1=birota"))

    def test_annotations_of_the_texts(self):
        words = ",".join(str(word.pk) for word in self.words[:2])
        create_sighting(words, self.other, "formule ?")
        create_reading_note(words, self.other, "Tournure fréquente.")
        hidden = create_reading_note(words, self.author, "Note masquée.")
        hide_content(hidden, self.reviewer)
        add_private_note(self.other, words, "Note privée secrète.")
        (sighting,) = self.get("sightings")[1]["results"]
        self.assertEqual((sighting["note"], sighting["status"]), ("formule ?", "open"))
        self.assertEqual(sighting["word_ids"], [word.pk for word in self.words[:2]])
        response, notes = self.get("reading_notes")
        self.assertEqual([note["text"] for note in notes["results"]], ["Tournure fréquente."])
        self.assertNotIn("secrète", response.content.decode())
        correction = AnalysisCorrection(token=self.words[0], lemma="consilius", reason="Lemme.")
        propose_correction(correction, self.other)
        self.assertEqual(self.get("corrections")[1]["count"], 0)
        review_correction(correction, self.reviewer, AnalysisCorrection.Status.VALIDATED)
        (item,) = self.get("corrections")[1]["results"]
        self.assertEqual((item["word_id"], item["lemma"]), (self.words[0].pk, "consilius"))

    def test_pages(self):
        NegativeSearch.objects.create(
            expression="autocinetum", query="term1=autocinetum", created_by=self.author
        )
        with mock.patch("api.views.PAGE_SIZE", 1):
            _response, first = self.get("negative_searches")
            self.assertTrue(first["next"].endswith("?page=2"))
            self.assertIsNone(first["previous"])
            _response, second = self.get("negative_searches", page=2)
            self.assertIsNone(second["next"])
            self.assertEqual(self.get("negative_searches", page=9)[0].status_code, 404)
