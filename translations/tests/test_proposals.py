from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from moderation.registry import uncounted_models
from moderation.services import can_comment
from translations.models import ChangeProposal, ProposedSentence
from translations.services import (
    create_proposal,
    create_step,
    decide_sentence,
    save_translation,
    withdraw_proposal,
)
from translations.steps import step_sentences

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class ProposalTestCase(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        # Not yet in a step: a proposal starts from the public text, not from this one.
        save_translation(self.version, self.third, "Cras abibimus.", self.author)

    def propose(self, texts=None, user=None):
        texts = texts or {self.first: "Pluit.", self.second: "Domi maneamus."}
        proposal = ChangeProposal(version=self.version, explanation="Subjonctif de souhait.")
        return create_proposal(proposal, user or self.other, texts)


class ProposalServicesTests(ProposalTestCase):
    def test_only_changed_sentences_are_proposed(self):
        proposal = self.propose(
            {
                self.first: " Pluit. ",
                self.second: "Domi maneamus.",
                self.third: "Cras proficiscemur.",
            }
        )
        self.assertEqual(proposal.base_step, self.version.steps.get())
        [sentence] = proposal.sentences.all()
        self.assertEqual(
            (sentence.segment, sentence.base_text, sentence.text),
            (self.second, "Domi manemus.", "Domi maneamus."),
        )
        self.assertTrue(sentence.is_pending)
        self.assertTrue(proposal.is_open)
        self.assertNotIn(ChangeProposal, uncounted_models())
        self.assertIn(ProposedSentence, uncounted_models())

    def test_who_may_propose(self):
        with self.assertRaises(PermissionDenied):
            self.propose(user=self.author)
        draft = make_version(self.reviewer, self.project)
        translate(draft)
        with self.assertRaises(PermissionDenied):
            create_proposal(
                ChangeProposal(version=draft, explanation="Non."),
                self.other,
                {self.first: "Imber."},
            )
        with self.assertRaises(ValidationError):
            self.propose({self.first: "Pluit."})
        self.assertFalse(ChangeProposal.objects.exists())

    def test_the_author_accepts_or_refuses_each_sentence(self):
        proposal = self.propose({self.second: "Domi maneamus.", self.third: "Cras abibimus hinc."})
        accepted, refused = proposal.sentences.all()
        with self.assertRaises(PermissionDenied):
            decide_sentence(accepted, self.other, accept=True)
        decide_sentence(accepted, self.author, accept=True)
        working = self.version.segments.get(segment=self.second)
        self.assertEqual((working.text, working.written_by), ("Domi maneamus.", self.other))
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        with self.assertRaises(ValidationError):
            decide_sentence(accepted, self.author, accept=False)
        decide_sentence(refused, self.author, accept=False)
        self.assertEqual(self.version.segments.get(segment=self.third).text, "Cras abibimus.")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ChangeProposal.Status.CLOSED)
        self.assertIsNotNone(proposal.closed_at)

        response = self.client.get(self.version.get_absolute_url())
        self.assertEqual(response.context["rows"][1]["saved"], "Domi manemus.")
        step = create_step(self.version, self.author, "Proposition de Quintus")
        self.assertEqual(step_sentences(step)[self.second.pk].written_by, self.other)
        self.assertContains(self.client.get(self.version.get_absolute_url()), "écrite par Quintus")

    def test_a_new_account_decides_on_a_proposal_with_a_link(self):
        newcomer = make_user(email="new@example.org", display_name="Novus", role=CONTRIBUTOR)
        version = make_published_version(newcomer, self.project)
        proposal = ChangeProposal(version=version, explanation="Voir https://example.org/ag.")
        proposal = create_proposal(proposal, self.other, {self.second: "Domi maneamus."})
        decide_sentence(proposal.sentences.get(), newcomer, accept=True)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ChangeProposal.Status.CLOSED)

    def test_the_proposer_withdraws_an_open_proposal(self):
        proposal = self.propose()
        with self.assertRaises(PermissionDenied):
            withdraw_proposal(proposal, self.author)
        withdraw_proposal(proposal, self.other)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ChangeProposal.Status.WITHDRAWN)
        with self.assertRaises(ValidationError):
            decide_sentence(proposal.sentences.get(), self.author, accept=True)


class ProposalPagesTests(ProposalTestCase):
    def test_propose_from_the_version_page(self):
        self.client.force_login(self.other)
        url = reverse("translations:proposal_create", args=[self.version.pk])
        self.assertContains(self.client.get(self.version.get_absolute_url()), url)
        page = self.client.get(url)
        self.assertContains(page, "Cras proficiscemur.")
        self.assertNotContains(page, "abibimus")
        data = {
            f"s{self.first.pk}": "Pluit.",
            f"s{self.second.pk}": "Domi maneamus.",
            f"s{self.third.pk}": "Cras proficiscemur.",
            "explanation": "Subjonctif de souhait.",
        }
        response = self.client.post(url, data)
        proposal = ChangeProposal.objects.get()
        self.assertRedirects(response, proposal.get_absolute_url())
        self.assertEqual(proposal.sentences.count(), 1)
        response = self.client.post(url, {**data, f"s{self.second.pk}": "Domi manemus."})
        self.assertContains(response, "Changez au moins une phrase")
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_the_proposal_page_and_the_decision(self):
        proposal = self.propose({self.second: "Domi maneamus.", self.third: "Cras abibimus hinc."})
        second, third = proposal.sentences.all()
        page = self.client.get(proposal.get_absolute_url())
        self.assertContains(page, "<del>manemus</del><ins>maneamus</ins>", html=True)
        self.assertFalse(page.context["can_decide"])
        self.assertEqual(
            [item["changed_since"] for item in page.context["sentences"]], [False, False]
        )
        self.assertNotContains(page, "Votre texte de travail a changé")

        self.client.force_login(self.author)
        page = self.client.get(proposal.get_absolute_url())
        self.assertTrue(page.context["can_decide"])
        self.assertEqual(
            [item["changed_since"] for item in page.context["sentences"]], [False, True]
        )
        self.assertContains(page, "Votre texte de travail a changé depuis cette proposition")
        decide = reverse("translations:proposed_sentence_decide", args=[second.pk])
        self.assertEqual(self.client.post(decide, {"decision": "maybe"}).status_code, 400)
        response = self.client.post(decide, {"decision": "accept"})
        self.assertRedirects(
            response,
            f"{proposal.get_absolute_url()}#proposee-{second.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.version.segments.get(segment=self.second).text, "Domi maneamus.")

        self.client.force_login(self.other)
        other_decide = reverse("translations:proposed_sentence_decide", args=[third.pk])
        self.assertEqual(self.client.post(other_decide, {"decision": "accept"}).status_code, 403)

    def test_discussion_and_list(self):
        proposal = self.propose()
        self.assertTrue(can_comment(self.reviewer, proposal))
        list_url = reverse("translations:proposal_list", args=[self.version.pk])
        self.assertContains(self.client.get(list_url), proposal.get_absolute_url())
        self.client.force_login(self.author)
        self.assertContains(
            self.client.get(self.version.get_absolute_url()), "1 proposition ouverte"
        )
        withdraw_proposal(proposal, self.other)
        proposal.refresh_from_db()
        self.assertFalse(can_comment(self.reviewer, proposal))
