from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from activity.models import Notification, Verb
from moderation.models import Comment
from translations.models import ChangeProposal
from translations.services import create_proposal, review_proposal

from .factories import make_published_version
from .test_versions import TranslationTestCase


class ReviewTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        self.proposal = create_proposal(
            ChangeProposal(version=self.version, explanation="Mieux."),
            self.other,
            {self.first: "Pluit multum.", self.second: "Domi mansimus."},
        )

    def test_review_is_told_to_the_author_of_the_proposal(self):
        review_proposal(self.proposal, self.reviewer, "approve")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.other, event__verb=Verb.PROPOSAL_REVIEWED
            ).exists()
        )

    def test_requesting_changes_needs_a_comment(self):
        with self.assertRaises(ValidationError):
            review_proposal(self.proposal, self.reviewer, "changes", "")

    def test_the_author_of_the_proposal_does_not_review_it(self):
        with self.assertRaises(PermissionDenied):
            review_proposal(self.proposal, self.other, "approve")

    def test_page_shows_reviews_and_a_thread_per_sentence(self):
        review_proposal(self.proposal, self.reviewer, "changes", "Le parfait ?")
        self.client.force_login(self.author)
        response = self.client.get(self.proposal.get_absolute_url())
        self.assertContains(response, "demande des changements")
        self.assertContains(response, "Répondre sur cette phrase")

    def test_message_on_one_sentence(self):
        proposed = self.proposal.sentences.first()
        self.client.force_login(self.author)
        url = reverse("moderation:comment", args=["translations", "proposedsentence", proposed.pk])
        response = self.client.post(url, {"text": "Pourquoi multum ?"})
        self.assertRedirects(response, proposed.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual(Comment.objects.get().content_object, proposed)

    def test_review_form(self):
        self.client.force_login(self.reviewer)
        url = reverse("translations:proposal_review", args=[self.proposal.pk])
        self.client.post(url, {"verdict": "approve"})
        self.assertEqual(self.proposal.reviews.get().verdict, "approve")
