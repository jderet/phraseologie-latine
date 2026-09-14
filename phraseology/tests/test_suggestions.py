from django.contrib.auth.models import AnonymousUser
from django.urls import reverse

from corpus.models import Token
from phraseology.models import Attestation
from phraseology.services import add_attestations, propose_unit, review_attestation, update_unit
from phraseology.suggestions import confirm_suggestion, page_suggestions

from .factories import evidence
from .test_frequency import AnalysedCorpusTestCase


def ids(words):
    return ",".join(str(word.pk) for word in words)


class SuggestionTestCase(AnalysedCorpusTestCase):
    def setUp(self):
        super().setUp()
        self.unit.schema = "capio -obj|nsubj:pass-> consilium"
        update_unit(self.unit, self.author)
        propose_unit(self.unit, self.author)
        self.unit.refresh_from_db()
        self.passages = [self.passage, self.second_passage]
        self.token_ids = {word.pk for word in [*self.words, *self.more_words]}
        self.reading = reverse("corpus:reading", args=[self.passage.edition.work.cts_id])

    def suggested(self, user):
        suggestions = page_suggestions(user, self.passages, self.token_ids, self.layer)
        return [(item.unit, item.words) for item in suggestions]


class PageSuggestionTests(SuggestionTestCase):
    def test_occurrences_of_the_schema_not_yet_attested(self):
        plural = (self.more_words[0].pk, self.more_words[1].pk)
        self.assertEqual(self.suggested(self.other), [(self.unit, plural)])
        (suggestion,) = page_suggestions(self.other, self.passages, self.token_ids, self.layer)
        self.assertEqual(suggestion.key, f"s_{self.unit.pk}_{plural[0]}_{plural[1]}")
        self.assertEqual(suggestion.css, "u k-none s-suggested t0")
        self.assertEqual(self.suggested(AnonymousUser()), [])

    def test_a_rejected_attestation_is_not_suggested_again(self):
        (attestation,) = add_attestations(self.unit, [evidence(*self.more_words[:2])], self.other)
        review_attestation(attestation, self.reviewer, Attestation.Status.REJECTED)
        self.assertEqual(self.suggested(self.other), [])

    def test_confirmed_in_the_core_and_outside(self):
        (proposed,) = confirm_suggestion(self.unit, ids(self.more_words[:2]), self.other)
        self.assertEqual(
            (proposed.level, proposed.status, proposed.origin),
            (Attestation.Level.VALIDATED, Attestation.Status.PROPOSED, Attestation.Origin.QUERY),
        )
        self.assertEqual(confirm_suggestion(self.unit, ids(self.more_words[:2]), self.other), [])
        outside = Token.objects.filter(edition__work__is_core=False).order_by("position")
        (found,) = confirm_suggestion(self.unit, ids(outside), self.other)
        self.assertEqual(found.level, Attestation.Level.AUTOMATIC)


class SuggestionViewTests(SuggestionTestCase):
    def test_the_reading_in_mode_annoter_shows_them(self):
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.reading), "s-suggested")
        response = self.client.get(self.reading, {"annoter": "1"})
        self.assertContains(response, "s-suggested")
        self.assertContains(response, f'data-o="s_{self.unit.pk}_')

    def test_the_panel_and_the_confirmation(self):
        self.client.force_login(self.other)
        words = ids(self.more_words[:2])
        panel = self.client.get(
            reverse("phraseology:suggestion_panel"),
            {"fiche": self.unit.pk, "mots": words, "fragment": "1"},
        )
        self.assertContains(panel, "Confirmer l’attestation")
        self.assertContains(panel, "un relecteur la validera")
        back = f"{self.reading}?annoter=1#p-1.2"
        confirm = reverse("phraseology:suggestion_confirm")
        response = self.client.post(confirm, {"unit": self.unit.pk, "words": words, "next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        self.assertTrue(self.unit.attestations.filter(passage=self.second_passage).exists())
