from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from corpus.models import Token
from moderation.models import Revision
from phraseology.frequency import occurrence_words, schema_matches
from phraseology.models import Attestation, Realization, Unit
from phraseology.schema import parse_schema
from phraseology.services import (
    propose_unit,
    review_attestation,
    review_attestations,
    save_part,
    survey_unit,
    update_unit,
)
from phraseology.survey import attestation_shapes

from .factories import set_status
from .test_frequency import AnalysedCorpusTestCase

SCHEMA = "capio -obj|nsubj:pass-> consilium"


class SurveyTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = SCHEMA
        update_unit(self.unit, self.author)
        propose_unit(self.unit, self.author)
        self.unit.refresh_from_db()

    def automatic(self):
        return self.unit.attestations.filter(level=Attestation.Level.AUTOMATIC)


class OccurrenceWordsTests(SurveyTestCase):
    def test_words_of_many_occurrences_at_once(self):
        edges = parse_schema("capio -obj-> consilium; consilium -amod-> bonus")
        roots = schema_matches(edges, self.layer).values_list("token_id", "part", "token__position")
        self.assertEqual(
            occurrence_words(roots, edges, self.layer), [tuple(w.pk for w in self.good_words)]
        )
        edges = parse_schema(SCHEMA)
        roots = schema_matches(edges, self.layer).values_list("token_id", "part", "token__position")
        self.assertEqual(len(occurrence_words(roots, edges, self.layer)), 4)


class SurveyServiceTests(SurveyTestCase):
    def test_the_core_occurrences_become_automatic_attestations(self):
        survey = survey_unit(self.unit, self.other)
        counts = (survey.found, survey.core_found, survey.added, survey.remaining)
        self.assertEqual(counts, (4, 3, 3, 0))
        self.assertEqual(survey.schema, SCHEMA)
        self.assertIn("LatinCy test 1.0", survey.corpus_version)
        added = list(self.automatic().order_by("pk"))
        outside = Token.objects.filter(edition__work__is_core=False).order_by("position")
        self.assertEqual(
            [list(attestation.tokens.order_by("position")) for attestation in added],
            [list(self.more_words[:2]), list(self.good_words[1:]), list(outside)],
        )
        for attestation in added:
            self.assertEqual(attestation.origin, Attestation.Origin.QUERY)
            self.assertEqual(attestation.status, Attestation.Status.PROPOSED)
            self.assertEqual(attestation.status_label, "repérée automatiquement")
            self.assertEqual(attestation.created_by, self.other)
        self.assertEqual(Revision.objects.filter(comment="Relevé automatique").count(), 3)

    def test_a_new_survey_leaves_known_and_rejected_occurrences_aside(self):
        survey_unit(self.unit, self.other)
        rejected = self.automatic().first()
        review_attestations(self.unit, [rejected.pk], self.reviewer, Attestation.Status.REJECTED)
        survey = survey_unit(self.unit, self.other)
        self.assertEqual((survey.found, survey.added), (4, 0))
        self.assertEqual(self.unit.attestations.count(), 4)

    def test_an_attestation_covering_more_words_counts_as_known(self):
        attestation = self.unit.attestations.get()
        attestation.tokens.set(self.words[:3])
        self.assertEqual(survey_unit(self.unit, self.other).added, 3)

    def test_a_survey_adds_a_limited_number_and_the_next_goes_on(self):
        with mock.patch("phraseology.services.SURVEY_LIMIT", 1):
            survey = survey_unit(self.unit, self.other)
            self.assertEqual((survey.added, survey.remaining), (1, 2))
            survey = survey_unit(self.unit, self.other)
            self.assertEqual((survey.added, survey.remaining), (1, 1))

    def test_who_may_survey_and_what_it_needs(self):
        draft = Unit.objects.create(reference_form="bellum gerere", created_by=self.author)
        with self.assertRaises(PermissionDenied):
            survey_unit(draft, self.other)
        with self.assertRaises(ValidationError):
            survey_unit(draft, self.author)
        self.layer.is_default = False
        self.layer.save()
        with self.assertRaises(ValidationError):
            survey_unit(self.unit, self.other)


class BatchReviewTests(SurveyTestCase):
    def setUp(self):
        super().setUp()
        survey_unit(self.unit, self.other)
        core = self.automatic().filter(passage__edition__work__is_core=True)
        self.ids = list(core.values_list("pk", flat=True))
        self.outside = self.automatic().get(passage__edition__work__is_core=False)

    def test_a_reviewer_validates_a_batch_and_places_it(self):
        realization = Realization(unit=self.unit, form="consilia capiunt")
        save_part(realization, self.author)
        revisions = review_attestations(
            self.unit,
            self.ids,
            self.reviewer,
            Attestation.Status.VALIDATED,
            realization=realization,
        )
        self.assertEqual(len(revisions), 2)
        for attestation in Attestation.objects.filter(pk__in=self.ids):
            self.assertEqual(attestation.status, Attestation.Status.VALIDATED)
            self.assertEqual(attestation.level, Attestation.Level.VALIDATED)
            self.assertEqual(attestation.realization, realization)
            self.assertEqual(attestation.reviewed_by, self.reviewer)

    def test_only_reviewers_and_only_the_core(self):
        with self.assertRaises(PermissionDenied):
            review_attestations(self.unit, self.ids, self.other, Attestation.Status.VALIDATED)
        outside = Attestation.objects.create(
            unit=self.unit,
            passage=self.seneca.works.get().editions.get().passages.get(),
            level=Attestation.Level.AUTOMATIC,
            origin=Attestation.Origin.QUERY,
            created_by=self.other,
        )
        revisions = review_attestations(
            self.unit, [outside.pk], self.reviewer, Attestation.Status.VALIDATED
        )
        self.assertEqual(revisions, [])
        outside.refresh_from_db()
        self.assertEqual(outside.status, Attestation.Status.PROPOSED)

    def test_outside_the_core_found_automatically_is_rejected_never_validated(self):
        with self.assertRaises(ValidationError):
            review_attestation(self.outside, self.reviewer, Attestation.Status.VALIDATED)
        revisions = review_attestations(
            self.unit, [self.outside.pk], self.reviewer, Attestation.Status.REJECTED
        )
        self.assertEqual(len(revisions), 1)
        self.outside.refresh_from_db()
        self.assertEqual(self.outside.status, Attestation.Status.REJECTED)
        self.assertEqual(self.outside.level, Attestation.Level.AUTOMATIC)

    def test_parts_of_another_unit_are_refused(self):
        other_unit = Unit.objects.create(reference_form="bellum gerere", created_by=self.author)
        realization = Realization.objects.create(unit=other_unit, form="bellum gerit")
        with self.assertRaises(ValueError):
            review_attestations(
                self.unit,
                self.ids,
                self.reviewer,
                Attestation.Status.VALIDATED,
                realization=realization,
            )


class ShapeTests(SurveyTestCase):
    def test_shapes_follow_word_order_insertions_and_passive(self):
        survey_unit(self.unit, self.other)
        original = self.unit.attestations.get(passage=self.passage)
        outside = Attestation.objects.create(
            unit=self.unit,
            passage=self.seneca.works.get().editions.get().passages.get(),
            created_by=self.other,
        )
        passive_words = list(outside.passage.tokens.order_by("position"))
        outside.tokens.set(passive_words)
        original.tokens.set([self.words[0], self.words[1], self.words[3]])
        ids = self.unit.attestations.values_list("pk", flat=True)
        shapes = attestation_shapes(ids, self.layer, self.unit.edges)
        self.assertEqual(shapes[original.pk], "consilium capio … abiret")
        self.assertEqual(sorted(shapes.values()).count("consilium capio"), 2)
        self.assertEqual(shapes[outside.pk], "consilium capio (passif)")


class SurveyPagesTests(SurveyTestCase):
    def url(self, name="unit_survey"):
        return reverse(f"phraseology:{name}", args=[self.unit.pk])

    def test_editors_launch_the_survey(self):
        self.client.force_login(self.other)
        page = self.client.get(self.url())
        self.assertContains(page, "pas encore fait")
        self.assertContains(page, "Relever les occurrences")
        response = self.client.post(self.url("unit_survey_run"), follow=True)
        self.assertContains(response, "3 attestations ajoutées au relevé.")
        self.assertContains(
            response, "4 occurrences repérées automatiquement, dont 3 dans le noyau"
        )
        self.assertContains(response, "consilium capio")
        self.assertNotContains(response, "Valider la sélection")

    def test_the_survey_is_shown_to_everyone_but_launched_by_editors(self):
        survey_unit(self.unit, self.other)
        page = self.client.get(self.url())
        self.assertContains(page, "Réalisations relevées")
        self.assertNotContains(page, "Relever de nouveau")
        self.assertEqual(self.client.post(self.url("unit_survey_run")).status_code, 302)
        set_status(self.unit, Unit.Status.DRAFT)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_a_reviewer_validates_a_page_of_attestations(self):
        survey_unit(self.unit, self.other)
        ids = [str(pk) for pk in self.automatic().values_list("pk", flat=True)]
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                self.url("unit_survey_review"), {"attestation": ids, "decision": "valider"}
            ).status_code,
            403,
        )
        self.client.force_login(self.reviewer)
        page = self.client.get(self.url())
        self.assertContains(page, "Valider la sélection")
        self.assertContains(page, f'name="attestation" value="{ids[0]}" checked')
        response = self.client.post(
            self.url("unit_survey_review"),
            {
                "attestation": ids,
                "decision": "valider",
                "statut": "a-examiner",
                "forme": "consilium capio",
            },
        )
        self.assertRedirects(
            response,
            f"{self.url()}?statut=a-examiner&forme=consilium+capio#examen",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.automatic().filter(status=Attestation.Status.VALIDATED).count(), 0)
        self.assertEqual(
            self.unit.attestations.filter(pk__in=ids, status=Attestation.Status.VALIDATED).count(),
            2,
        )
        page = self.client.get(self.url(), {"statut": "validees"})
        self.assertContains(page, "Validée ·", count=2)
        self.assertNotContains(page, "Repérée automatiquement")

    def test_the_unit_page_links_to_the_survey(self):
        survey_unit(self.unit, self.other)
        page = self.client.get(self.unit.get_absolute_url())
        self.assertContains(page, self.url())
        self.assertContains(page, "2 attestations du noyau à examiner dans le relevé")
        self.assertContains(page, "1 attestation repérée automatiquement hors du noyau")
        self.assertNotContains(page, "Herc. F.")

    def test_outside_the_core_attestations_are_shown_as_found_automatically(self):
        survey_unit(self.unit, self.other)
        outside = self.automatic().get(passage__edition__work__is_core=False)
        self.client.force_login(self.reviewer)
        page = self.client.get(self.url(), {"portee": "hors-noyau"})
        self.assertContains(page, "Sen. Herc. F. 1")
        self.assertContains(page, "Repérée automatiquement ·")
        self.assertContains(page, "ne sont jamais validées")
        self.assertContains(page, "consilium capio (passif)")
        self.assertNotContains(page, "Valider la sélection")
        self.assertNotContains(page, "À examiner")
        self.assertContains(page, f'name="attestation" value="{outside.pk}">')
        response = self.client.post(
            self.url("unit_survey_review"),
            {"attestation": [outside.pk], "decision": "rejeter", "portee": "hors-noyau"},
        )
        self.assertRedirects(
            response, f"{self.url()}?portee=hors-noyau#examen", fetch_redirect_response=False
        )
        outside.refresh_from_db()
        self.assertEqual(outside.status, Attestation.Status.REJECTED)
