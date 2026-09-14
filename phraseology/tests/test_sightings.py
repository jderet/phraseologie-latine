from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from phraseology.models import Sighting, Unit
from phraseology.services import propose_unit
from phraseology.sightings import create_sighting, dismiss_sighting, page_sightings

from .test_frequency import AnalysedCorpusTestCase


def ids(words):
    return ",".join(str(word.pk) for word in words)


class SightingTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        self.unit.refresh_from_db()
        self.reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])


class SightingServiceTests(SightingTestCase):
    def test_a_sighting_on_the_page_then_dismissed(self):
        sighting = create_sighting(ids(self.words[2:4]), self.other, "ut abiret ?")
        self.assertEqual((sighting.status, sighting.passage), (Sighting.Status.OPEN, self.passage))
        marks = page_sightings([self.passage], {word.pk for word in self.words})
        key = f"r_{sighting.pk}_{self.words[2].pk}_{self.words[3].pk}"
        self.assertEqual([mark.key for mark in marks], [key])
        self.assertEqual(marks[0].css, "u k-none s-sighting t0")
        with self.assertRaises(PermissionDenied):
            dismiss_sighting(sighting, self.other)
        dismiss_sighting(sighting, self.reviewer)
        sighting.refresh_from_db()
        self.assertEqual(sighting.status, Sighting.Status.DISMISSED)
        self.assertEqual(page_sightings([self.passage], {word.pk for word in self.words}), [])
        with self.assertRaises(ValidationError):
            dismiss_sighting(sighting, self.reviewer)


class SightingViewTests(SightingTestCase):
    def test_recorded_in_the_reading_and_attached_to_an_entry(self):
        self.client.force_login(self.other)
        words = ids(self.more_words[:2])
        create = reverse("phraseology:sighting_create")
        panel = self.client.get(create, {"mots": words, "fragment": "1"})
        self.assertContains(panel, "Enregistrer le repérage")
        response = self.client.post(
            create, {"words": words, "note": "au pluriel", "next": self.reading}
        )
        self.assertRedirects(response, self.reading, fetch_redirect_response=False)
        sighting = Sighting.objects.get()
        annotating = self.client.get(self.reading, {"annoter": "1"})
        self.assertContains(annotating, f'data-o="r_{sighting.pk}_')
        self.assertNotContains(self.client.get(self.reading), f'data-o="r_{sighting.pk}_')
        listing = self.client.get(reverse("phraseology:sightings"))
        self.assertContains(listing, "au pluriel")
        self.assertContains(listing, f"reperage={sighting.pk}")
        selection = self.client.get(
            reverse("phraseology:annotate_selection"),
            {"mots": words, "reperage": sighting.pk, "q": "consilium", "fragment": "1"},
        )
        self.assertContains(selection, f'name="sighting" value="{sighting.pk}"')
        attach = reverse("phraseology:annotate_attach")
        data = {"unit": self.unit.pk, "words": words, "sighting": sighting.pk, "next": self.reading}
        self.client.post(attach, data)
        sighting.refresh_from_db()
        self.assertEqual(sighting.status, Sighting.Status.ATTACHED)
        self.assertEqual(sighting.attestation.passage, self.second_passage)
        self.assertEqual(sighting.attestation.unit, self.unit)

    def test_a_new_entry_made_from_a_sighting(self):
        words = ids(self.words[2:4])
        sighting = create_sighting(words, self.other)
        self.client.force_login(self.other)
        data = {
            "reference_form": "ut abiret",
            "definition": "pour s’en aller",
            "attestation": words,
            "reperage": sighting.pk,
        }
        self.client.post(reverse("phraseology:unit_create"), data)
        unit = Unit.objects.get(reference_form="ut abiret")
        sighting.refresh_from_db()
        self.assertEqual(sighting.status, Sighting.Status.ATTACHED)
        self.assertEqual(sighting.attestation.unit, unit)
