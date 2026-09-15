from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from justifications.models import Challenge, Justification
from justifications.services import close_challenge, create_challenge, withdraw_challenge
from moderation.models import Comment, Revision, Vote
from moderation.registry import uncounted_models
from moderation.services import (
    can_comment,
    can_vote,
    cast_vote,
    hide_content,
    post_comment,
    revert_to,
    save_with_revision,
    vote_summary,
)
from translations.services import create_step, publish_version
from translations.tests.factories import make_version, translate

from .test_services import JustificationTestCase

ARGUMENT = "Le futur conviendrait mieux : manebimus."


class ChallengeTestCase(JustificationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.voter = make_user(
            email="voter@example.org", display_name="Gaius", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.newcomer = make_user(email="new@example.org", display_name="Novus", role=CONTRIBUTOR)

    def setUp(self):
        super().setUp()
        publish_version(self.version, self.author)
        self.version.refresh_from_db()

    def contest(self, user=None, excerpt="manemus", evidences=None, justification=None):
        challenge = Challenge(
            translated_segment=self.translated,
            justification=justification,
            latin_excerpt=excerpt,
            argument=ARGUMENT,
        )
        return create_challenge(challenge, user or self.other, evidences or [])


class ChallengeServicesTests(ChallengeTestCase):
    def test_a_published_choice_is_contested_with_counter_examples(self):
        justification = self.justify()
        challenge = self.contest(justification=justification, evidences=[self.attestation()])
        self.assertEqual((challenge.status, challenge.locate()), (Challenge.Status.OPEN, (5, 12)))
        evidence = challenge.evidences.get()
        self.assertEqual((evidence.challenge, evidence.justification), (challenge, None))
        self.assertTrue(Justification.objects.get(pk=justification.pk).is_challenged)
        self.assertNotIn(Challenge, uncounted_models())
        self.assertNotIn(Comment, uncounted_models())

    def test_who_may_contest_what(self):
        with self.assertRaises(PermissionDenied):
            self.contest(user=self.author)
        with self.assertRaises(ValidationError):
            self.contest(excerpt="manebimus")
        draft = make_version(self.author, self.project)
        translate(draft)
        self.translated = draft.segments.get(segment=self.second)
        with self.assertRaises(PermissionDenied):
            self.contest()

    def test_votes_are_indicative_and_personal(self):
        challenge = self.contest()
        cast_vote(challenge, self.voter, 1)
        cast_vote(challenge, self.reviewer, -1)
        self.assertEqual(
            vote_summary(self.voter, challenge), {"for": 1, "against": 1, "current": 1}
        )
        cast_vote(challenge, self.voter, -1)
        self.assertEqual(vote_summary(self.voter, challenge)["against"], 2)
        cast_vote(challenge, self.voter, 0)
        self.assertEqual(
            vote_summary(self.voter, challenge), {"for": 0, "against": 1, "current": None}
        )
        for user in (self.other, self.author, self.newcomer, AnonymousUser()):
            with self.subTest(user=str(user)):
                self.assertFalse(can_vote(user, challenge))
                with self.assertRaises(PermissionDenied):
                    cast_vote(challenge, user, 1)
        closed = close_challenge(challenge, self.reviewer, Challenge.Status.DISMISSED, "Non.")
        self.assertFalse(can_vote(self.voter, closed))

    def test_discussion(self):
        challenge = self.contest()
        comment = post_comment(challenge, self.author, "Manemus : nous restons maintenant.")
        self.assertEqual(Revision.objects.for_object(comment).get().action, Revision.Action.CREATE)
        with self.assertRaises(ValidationError):
            post_comment(challenge, self.newcomer, "voir https://example.org")
        self.assertFalse(can_comment(self.author, self.version))
        with self.assertRaises(PermissionDenied):
            post_comment(self.version, self.author, "Bonjour.")
        closed = close_challenge(challenge, self.reviewer, Challenge.Status.DISMISSED, "Non.")
        with self.assertRaises(PermissionDenied):
            post_comment(closed, self.voter, "Trop tard ?")

    def test_closing_and_withdrawing(self):
        challenge = self.contest()
        with self.assertRaises(PermissionDenied):
            close_challenge(challenge, self.voter, Challenge.Status.UPHELD, "Oui.")
        closed = close_challenge(challenge, self.reviewer, Challenge.Status.UPHELD, "Le futur.")
        self.assertEqual(
            (closed.status, closed.closed_by), (Challenge.Status.UPHELD, self.reviewer)
        )
        self.assertIsNotNone(closed.closed_at)
        with self.assertRaises(ValidationError):
            close_challenge(closed, self.reviewer, Challenge.Status.DISMISSED, "Non.")
        second = self.contest(user=self.voter)
        with self.assertRaises(PermissionDenied):
            withdraw_challenge(second, self.other)
        self.assertEqual(withdraw_challenge(second, self.voter).status, Challenge.Status.WITHDRAWN)

    def test_a_revert_never_reopens_a_challenge(self):
        challenge = self.contest()
        creation = Revision.objects.for_object(challenge).get()
        challenge.argument = "Autre argument."
        save_with_revision(challenge, self.other)
        close_challenge(challenge, self.reviewer, Challenge.Status.DISMISSED, "Non.")
        revert_to(creation, self.reviewer)
        challenge = Challenge.objects.get(pk=challenge.pk)
        self.assertEqual(
            (challenge.argument, challenge.status), (ARGUMENT, Challenge.Status.DISMISSED)
        )


class ChallengePagesTests(ChallengeTestCase):
    def test_contest_from_the_version_page(self):
        create_url = reverse("justifications:challenge_create", args=[self.translated.pk])
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.version.get_absolute_url()), create_url)
        self.assertContains(self.client.get(create_url), 'value="Domi manemus."')
        data = {
            "latin_excerpt": "manemus",
            "argument": ARGUMENT,
            "attestation": [str(self.words[1].pk)],
            "references-TOTAL_FORMS": "2",
            "references-INITIAL_FORMS": "0",
            "references-MIN_NUM_FORMS": "0",
            "references-MAX_NUM_FORMS": "5",
        }
        response = self.client.post(create_url, data)
        challenge = Challenge.objects.get()
        self.assertRedirects(response, challenge.get_absolute_url())
        self.assertEqual(challenge.evidences.count(), 1)

        self.client.force_login(self.author)
        page = self.client.get(self.version.get_absolute_url())
        self.assertContains(page, challenge.get_absolute_url())
        self.assertContains(page, "une justification est attendue")
        self.assertNotContains(page, create_url)
        self.assertEqual(self.client.get(create_url).status_code, 403)
        self.assertContains(self.client.get(challenge.get_absolute_url()), "justifiez-le")

    def test_votes_discussion_and_decision_on_the_page(self):
        challenge = self.contest()
        url = challenge.get_absolute_url()
        vote_url = reverse("moderation:vote", args=["justifications", "challenge", challenge.pk])
        comment_url = reverse(
            "moderation:comment", args=["justifications", "challenge", challenge.pk]
        )

        self.client.force_login(self.voter)
        page = self.client.get(url)
        self.assertContains(page, vote_url)
        self.assertContains(page, comment_url)
        response = self.client.post(vote_url, {"value": "1"})
        self.assertRedirects(response, f"{url}#votes", fetch_redirect_response=False)
        self.assertEqual(Vote.objects.get().value, 1)
        response = self.client.post(comment_url, {"text": "Je suis d’accord."}, follow=True)
        self.assertContains(response, "Je suis d’accord.")
        self.assertEqual(self.client.post(vote_url, {"value": "7"}).status_code, 400)

        self.client.force_login(self.other)
        self.assertEqual(self.client.post(vote_url, {"value": "1"}).status_code, 403)
        self.assertNotContains(self.client.get(url), vote_url)

        close_url = reverse("justifications:challenge_close", args=[challenge.pk])
        decision = {"decision": "upheld", "resolution": "Le futur s’impose."}
        self.assertEqual(self.client.post(close_url, decision).status_code, 403)
        self.client.force_login(self.reviewer)
        self.assertRedirects(self.client.post(close_url, decision), url)
        page = self.client.get(url)
        self.assertContains(page, "Le futur s’impose.")
        self.assertContains(page, "La discussion est close.")
        self.assertEqual(self.client.post(comment_url, {"text": "Encore ?"}).status_code, 403)

    def test_list_and_hidden_challenges(self):
        challenge = self.contest()
        list_url = reverse("justifications:challenge_list")
        self.assertContains(self.client.get(list_url), challenge.get_absolute_url())
        hide_content(challenge, self.reviewer)
        self.assertNotContains(self.client.get(list_url), challenge.get_absolute_url())
        self.assertEqual(self.client.get(challenge.get_absolute_url()).status_code, 404)

    def test_drafts_cannot_be_contested_or_discussed(self):
        draft = make_version(self.author, self.project)
        translate(draft)
        translated = draft.segments.get(segment=self.second)
        self.client.force_login(self.other)
        url = reverse("justifications:challenge_create", args=[translated.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        comment_url = reverse(
            "moderation:comment", args=["translations", "translationversion", draft.pk]
        )
        self.assertEqual(self.client.post(comment_url, {"text": "Bonjour."}).status_code, 404)

    def test_a_justification_can_be_contested(self):
        justification = self.justify()
        # Others see the justification once a step has brought it out.
        create_step(self.version, self.author, "Justification")
        self.client.force_login(self.other)
        page = self.client.get(justification.get_absolute_url())
        self.assertContains(page, f"?justification={justification.pk}")
        self.contest(justification=justification)
        self.client.force_login(self.author)
        page = self.client.get(self.version.get_absolute_url())
        self.assertContains(page, "contestée")
        self.assertNotContains(page, "une justification est attendue")
