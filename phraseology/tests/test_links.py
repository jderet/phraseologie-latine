from django.core.exceptions import ValidationError
from django.urls import reverse

from justifications.models import Justification, Strength
from justifications.services import (
    attestation_evidence,
    create_justification,
    update_justification,
)
from moderation.models import Revision
from phraseology.models import Unit
from translations.services import publish_version, save_translation
from translations.tests.factories import make_project, make_source_text, make_version

from .factories import make_unit, set_status
from .test_spotting import SpottingTestCase

LATIN = "Consilium celeriter cepit."
EXCERPT = "Consilium celeriter cepit"
REFERENCES = {
    "references-TOTAL_FORMS": "2",
    "references-INITIAL_FORMS": "0",
    "references-MIN_NUM_FORMS": "0",
    "references-MAX_NUM_FORMS": "5",
}


class LinkTestCase(SpottingTestCase):
    def setUp(self):
        super().setUp()
        source = make_source_text(self.author, sentences=("Ils décident vite.",))
        self.version = make_version(self.author, make_project(self.author, source))
        self.segment = source.segments.get()
        save_translation(self.version, self.segment, LATIN, self.author)
        self.translated = self.version.segments.get()
        self.attestation = self.unit.attestations.get()

    def justify(self, units=(), evidences=None):
        if evidences is None:
            evidences = [attestation_evidence(self.attestation)]
        justification = Justification(
            translated_segment=self.translated, latin_excerpt=EXCERPT, strength=Strength.ATTESTED
        )
        return create_justification(justification, self.author, evidences, units=units)


class LinkServicesTests(LinkTestCase):
    def test_a_justification_cites_a_unit_and_one_of_its_attestations(self):
        justification = self.justify(units=[self.unit])
        self.assertEqual(list(justification.units.all()), [self.unit])
        evidence = justification.evidences.get()
        self.assertEqual(evidence.attestation, self.attestation)
        self.assertEqual(list(evidence.tokens.order_by("position")), self.words[:2])
        revision = Revision.objects.for_object(justification).get()
        self.assertEqual(revision.after["units"], [self.unit.pk])

    def test_the_links_are_changed_with_a_revision(self):
        justification = self.justify()
        revision = update_justification(justification, self.author, units=[self.unit])
        self.assertEqual(revision.after["units"], [self.unit.pk])
        self.assertIsNone(update_justification(justification, self.author, units=[self.unit]))

    def test_only_units_the_author_sees_are_cited(self):
        hidden_draft = make_unit(self.other, self.more_words[:2], reference_form="consilia capere")
        with self.assertRaises(ValidationError):
            self.justify(units=[hidden_draft])


class LinkPagesTests(LinkTestCase):
    def create_url(self):
        return reverse("justifications:create", args=[self.version.pk, self.segment.pk])

    def test_justifying_with_a_known_unit(self):
        self.client.force_login(self.author)
        panel = self.client.get(
            reverse("phraseology:units_in_sentence", args=[self.version.pk, self.segment.pk]),
            {"fragment": "1"},
        )
        link = f"{self.create_url()}?unite={self.unit.pk}&amp;extrait=Consilium%20celeriter%20cepit"
        self.assertContains(panel, f"{link}&amp;debut=0")
        query = {"unite": self.unit.pk, "extrait": EXCERPT, "debut": "0"}
        page = self.client.get(self.create_url(), query)
        self.assertContains(page, f'name="attestation_unite" value="{self.attestation.pk}"')
        self.assertRegex(page.content.decode(), rf'name="units" value="{self.unit.pk}"[^>]*checked')
        data = REFERENCES | {
            "latin_excerpt": EXCERPT,
            "source_excerpt": "",
            "strength": "1",
            "comment": "",
            "units": [self.unit.pk],
            "attestation_unite": [self.attestation.pk],
        }
        url = f"{self.create_url()}?unite={self.unit.pk}&debut=0"
        response = self.client.post(url, data)
        justification = Justification.objects.get()
        self.assertRedirects(response, justification.get_absolute_url())
        self.assertEqual(justification.evidences.get().attestation, self.attestation)
        detail = self.client.get(justification.get_absolute_url())
        self.assertContains(detail, "Fiches phraséologiques")
        self.assertContains(detail, "consilium capere")
        self.assertContains(detail, "attestation reprise d’une fiche phraséologique")

    def test_the_panel_offers_no_link_to_other_readers(self):
        publish_version(self.version, self.author)
        set_status(self.unit, Unit.Status.PROPOSED)
        self.client.force_login(self.other)
        panel = self.client.get(
            reverse("phraseology:units_in_sentence", args=[self.version.pk, self.segment.pk]),
            {"fragment": "1"},
        )
        self.assertContains(panel, "consilium capere")
        self.assertNotContains(panel, "Justifier avec cette fiche")

    def test_the_unit_shows_the_translations_that_use_it(self):
        set_status(self.unit, Unit.Status.PROPOSED)
        justification = self.justify(units=[self.unit])
        self.assertNotContains(self.client.get(self.unit.get_absolute_url()), f"« {EXCERPT} »")
        publish_version(self.version, self.author)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, "Traductions qui l’emploient")
        self.assertContains(page, f"« {EXCERPT} »")
        self.assertContains(page, justification.get_absolute_url())

    def test_editing_the_cited_units(self):
        justification = self.justify()
        self.client.force_login(self.author)
        url = reverse("justifications:edit", args=[justification.pk])
        self.assertContains(self.client.get(url), f'name="units" value="{self.unit.pk}"')
        data = {"latin_excerpt": EXCERPT, "source_excerpt": "", "strength": "1", "comment": ""}
        self.client.post(url, data | {"units": [self.unit.pk]})
        self.assertEqual(list(justification.units.all()), [self.unit])
