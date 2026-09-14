from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from corpus.models import Edition
from phraseology.models import Attestation, Kind, Unit, UsageMark
from phraseology.reading import (
    AUTOMATIC,
    MAX_TRACKS,
    PROPOSED,
    VALIDATED,
    ReadingFilters,
    assign_tracks,
    page_attestations,
    page_occurrences,
    reading_filters,
)
from phraseology.services import (
    add_attestations,
    propose_unit,
    record_automatic_attestations,
    review_attestation,
)

from .factories import evidence, make_unit
from .test_frequency import AnalysedCorpusTestCase


def occurrence(start, end, pk):
    return SimpleNamespace(start=start, end=end, attestation=SimpleNamespace(pk=pk), track=0)


class TrackTests(SimpleTestCase):
    def test_occurrences_sharing_words_are_drawn_one_under_the_other(self):
        long, inner, later, far = (
            occurrence(1, 5, 1),
            occurrence(2, 3, 2),
            occurrence(4, 6, 3),
            occurrence(7, 8, 4),
        )
        assign_tracks([far, later, inner, long])
        self.assertEqual([item.track for item in (long, inner, later, far)], [0, 1, 1, 0])

    def test_the_tracks_are_limited(self):
        nested = [occurrence(1, 10 - index, index) for index in range(6)]
        assign_tracks(nested)
        self.assertEqual([item.track for item in nested], [0, 1, 2, 3, 3, 3])
        self.assertEqual(MAX_TRACKS, 4)


class FilterTests(SimpleTestCase):
    def request(self, session=None, **params):
        request = RequestFactory().get("/", params)
        SessionMiddleware(lambda request: None).process_request(request)
        if session is not None:
            request.session = session
        return request

    def test_by_default_what_people_found_is_underlined(self):
        self.assertEqual(reading_filters(self.request()), ReadingFilters((VALIDATED, PROPOSED)))

    def test_the_choice_is_remembered_for_the_session(self):
        sent = self.request(
            filtres="1",
            statut=["automatic", "everything"],
            type="formula",
            marque="poetic",
            registre="elevated",
        )
        chosen = ReadingFilters((AUTOMATIC,), ("formula",), ("poetic",), ("elevated",))
        self.assertEqual(reading_filters(sent), chosen)
        self.assertEqual(reading_filters(self.request(sent.session)), chosen)
        self.assertTrue(reading_filters(self.request(sent.session, filtres="defaut")).is_default)
        self.assertTrue(reading_filters(self.request(sent.session)).is_default)


class PageAttestationTests(AnalysedCorpusTestCase):
    def keys(self, user, **options):
        passages = [self.passage, self.second_passage]
        return sorted(item.pk for item in page_attestations(user, passages, **options))

    def test_a_draft_is_underlined_for_its_creator_only(self):
        attestation = self.unit.attestations.get()
        self.assertEqual(self.keys(self.author), [attestation.pk])
        self.assertEqual(self.keys(self.other), [])
        self.assertEqual(self.keys(AnonymousUser()), [])
        propose_unit(self.unit, self.author)
        self.assertEqual(self.keys(AnonymousUser()), [attestation.pk])

    def test_statuses_types_marks_and_registers(self):
        propose_unit(self.unit, self.author)
        manual = self.unit.attestations.get()
        (found,) = record_automatic_attestations(
            self.unit, [(self.more_words[0].pk, self.more_words[1].pk)], self.author
        )
        everything = ReadingFilters((VALIDATED, PROPOSED, AUTOMATIC))
        self.assertEqual(self.keys(self.other), [manual.pk])
        self.assertEqual(self.keys(self.other, filters=everything), sorted([manual.pk, found.pk]))
        review_attestation(found, self.reviewer, Attestation.Status.VALIDATED)
        review_attestation(manual, self.reviewer, Attestation.Status.REJECTED)
        self.assertEqual(self.keys(self.other, filters=everything), [found.pk])
        Unit.objects.filter(pk=self.unit.pk).update(
            kind=Kind.FORMULA, usage_marks=[UsageMark.POETIC], register="elevated"
        )
        chosen = ReadingFilters(
            (VALIDATED,), kinds=("formula",), marks=("poetic",), registers=("elevated",)
        )
        self.assertEqual(self.keys(self.other, filters=chosen), [found.pk])
        for other in (
            ReadingFilters((VALIDATED,), kinds=("fixed",)),
            ReadingFilters((VALIDATED,), marks=("late",)),
            ReadingFilters((VALIDATED,), registers=("familiar",)),
        ):
            self.assertEqual(self.keys(self.other, filters=other), [])

    def test_occurrences_that_share_a_word(self):
        propose_unit(self.unit, self.author)
        second = make_unit(self.other, self.words[1:3], reference_form="cepit ut")
        propose_unit(second, self.other)
        occurrences = page_occurrences(
            page_attestations(self.other, [self.passage]),
            {word.pk for word in self.words},
            {self.passage.pk: "1.1"},
        )
        words = [word.pk for word in self.words]
        self.assertEqual(
            [(item.unit.pk, item.words, item.track) for item in occurrences],
            [(self.unit.pk, words[:2], 0), (second.pk, words[1:3], 1)],
        )
        self.assertEqual(occurrences[0].css, "u k-none s-proposed t0")
        self.assertEqual(occurrences[0].reference, "1.1")


class ReadingPageTests(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        propose_unit(self.unit, self.author)
        Edition.objects.filter(pk=self.passage.edition_id).update(
            citation_scheme=["book", "section"]
        )
        self.work_id = self.passage.edition.work.cts_id

    def url(self, part=None):
        if part is None:
            return reverse("corpus:reading", args=[self.work_id])
        return reverse("corpus:reading_part", args=[self.work_id, part])

    def test_the_words_of_an_attestation_are_underlined(self):
        response = self.client.get(self.url())
        attestation = self.unit.attestations.get()
        first = self.words[0]
        self.assertContains(
            response,
            f'<span class="u k-none s-proposed t0" data-o="{attestation.pk}">'
            f'<span data-t="{first.pk}">Consilium</span></span>',
            html=True,
        )
        self.assertContains(response, f'<span data-t="{self.words[2].pk}">ut</span>', html=True)
        self.assertContains(response, self.unit.get_absolute_url())
        self.assertContains(response, "js/reading.js")

    def test_the_filters_are_applied_and_remembered(self):
        response = self.client.get(self.url(), {"filtres": "1", "statut": "validated"})
        self.assertNotContains(response, 'class="u ')
        self.assertContains(response, "Aucune attestation sur cette page avec ces réglages.")
        self.assertNotContains(self.client.get(self.url()), 'class="u ')
        self.assertContains(self.client.get(self.url(), {"filtres": "defaut"}), 'class="u ')

    def test_one_unit_followed_from_occurrence_to_occurrence(self):
        later = (evidence(*self.more_words[:2]), evidence(*self.good_words[1:]))
        add_attestations(self.unit, later, self.author)
        pk = self.unit.pk
        with mock.patch("corpus.reading.PAGE_SIZE", 1):
            response = self.client.get(self.url("1.2"), {"fiche": pk})
        self.assertContains(response, f'href="{self.url("1.1")}?fiche={pk}#p-1.1"')
        self.assertContains(response, f'href="{self.url("1.3")}?fiche={pk}#p-1.3"')
        self.assertContains(response, "3 occurrences dans l’œuvre")
