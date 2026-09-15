from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from moderation.registry import can_view, uncounted_models
from moderation.services import can_comment
from translations.models import SourceChange, SourceProposal
from translations.services import (
    add_proposal_operation,
    adopt_source_proposal,
    change_source_text,
    rebase_source_proposal,
    refuse_source_proposal,
    send_source_proposal,
    undo_proposal_operation,
    withdraw_source_proposal,
)

from .factories import SENTENCES, make_published_version
from .test_sources import edit, insert, merge, split
from .test_versions import TranslationTestCase


def expecting(operation, *texts):
    return {**operation, "expected": list(texts)}


class SourceProposalServicesTests(TranslationTestCase):
    def texts(self):
        return list(self.source.segments.current().values_list("text", flat=True))

    def prepare(self):
        add_proposal_operation(
            self.source,
            expecting(split(1, "Nous restons", "à la maison."), "Nous restons à la maison."),
            self.other,
        )
        # The numbers follow the proposal: the second part is now sentence 3.
        return add_proposal_operation(
            self.source, expecting(edit(2, "à la maison, au chaud."), "à la maison."), self.other
        )

    def test_a_proposal_is_prepared_in_private_then_sent(self):
        proposal = self.prepare()
        self.assertEqual(
            (proposal.status, len(proposal.operations), proposal.base_state), ("preparing", 2, 0)
        )
        self.assertTrue(can_view(self.other, proposal))
        self.assertFalse(can_view(self.author, proposal))
        self.assertFalse(can_view(AnonymousUser(), proposal))
        self.assertNotIn(SourceProposal, uncounted_models())
        self.assertEqual(self.texts(), list(SENTENCES))

        undo_proposal_operation(proposal, self.other)
        proposal.refresh_from_db()
        self.assertEqual(len(proposal.operations), 1)
        with self.assertRaises(ValidationError) as caught:
            send_source_proposal(proposal, self.other, " ")
        self.assertEqual(caught.exception.code, "no_explanation")
        send_source_proposal(proposal, self.other, "Des phrases plus courtes.")
        proposal.refresh_from_db()
        self.assertTrue(proposal.is_open)
        self.assertTrue(can_view(AnonymousUser(), proposal))
        self.assertTrue(can_comment(self.author, proposal))

    def test_whoever_added_the_text_adopts_a_proposal_as_a_whole(self):
        version = make_published_version(self.author, self.project)
        proposal = self.prepare()
        send_source_proposal(proposal, self.other, "Des phrases plus courtes.")
        with self.assertRaises(PermissionDenied):
            adopt_source_proposal(proposal, self.other)
        adopt_source_proposal(proposal, self.author)
        proposal.refresh_from_db()
        self.assertEqual((proposal.status, proposal.decided_by), ("adopted", self.author))
        self.assertEqual(
            self.texts(),
            ["Il pleut.", "Nous restons", "à la maison, au chaud.", "Demain, nous partirons."],
        )
        self.assertEqual(
            [
                (change.kind, change.author, change.adopted_by, change.proposal)
                for change in SourceChange.objects.order_by("number")
            ],
            [
                ("split", self.other, self.author, proposal),
                ("edit", self.other, self.author, proposal),
            ],
        )
        self.assertEqual(version.segments.current().get(segment__order=2).text, "Domi manemus.")
        with self.assertRaises(ValidationError) as caught:
            refuse_source_proposal(proposal, self.author)
        self.assertEqual(caught.exception.code, "closed")

    def test_a_proposal_is_taken_up_again_when_the_text_changes(self):
        proposal = self.prepare()
        send_source_proposal(proposal, self.other, "Des phrases plus courtes.")
        change_source_text(self.source, insert(0, "D’abord."), self.author)
        with self.assertRaises(ValidationError) as caught:
            adopt_source_proposal(proposal, self.author)
        self.assertEqual(caught.exception.code, "stale_proposal")
        # Each change finds again the sentence it expects, one place further.
        rebase_source_proposal(proposal, self.other)
        proposal.refresh_from_db()
        self.assertEqual(
            (proposal.base_state, [operation["index"] for operation in proposal.operations]),
            (1, [2, 3]),
        )
        adopt_source_proposal(proposal, self.reviewer)
        self.assertEqual(self.texts()[2:4], ["Nous restons", "à la maison, au chaud."])

        # A change to the very sentence a proposal changes leaves it nowhere to apply.
        other = add_proposal_operation(
            self.source, expecting(merge(0), "D’abord.", "Il pleut."), self.other
        )
        send_source_proposal(other, self.other, "Une seule phrase.")
        change_source_text(self.source, edit(0, "Tout d’abord."), self.author)
        with self.assertRaises(ValidationError) as caught:
            rebase_source_proposal(other, self.other)
        self.assertEqual(caught.exception.code, "no_longer_applies")
        refuse_source_proposal(other, self.author)
        other.refresh_from_db()
        self.assertEqual(other.status, "refused")

    def test_who_may_propose_send_and_withdraw(self):
        for user in (self.author, self.reviewer):
            with self.subTest(user=user.email), self.assertRaises(PermissionDenied):
                add_proposal_operation(self.source, merge(0), user)
        proposal = add_proposal_operation(self.source, merge(0), self.other)
        with self.assertRaises(PermissionDenied):
            send_source_proposal(proposal, self.author, "Intrus.")
        withdraw_source_proposal(proposal, self.other)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, "withdrawn")
        # Never sent, it stays private.
        self.assertFalse(can_view(self.author, proposal))


class SourceProposalPagesTests(TranslationTestCase):
    def url(self, name, *args):
        return reverse(f"translations:{name}", args=args)

    def test_a_proposal_is_prepared_sent_and_adopted_through_the_pages(self):
        sentences = self.url("source_sentences", self.source.pk)
        split_url = self.url("source_sentence_split", self.source.pk, 2)
        self.client.force_login(self.other)
        page = self.client.get(sentences)
        self.assertContains(page, "Vos changements forment une proposition")
        self.assertContains(page, split_url)
        response = self.client.post(split_url, {"state": 0, "parts": "Nous restons\nà la maison."})
        self.assertRedirects(response, sentences + "#phrase-2")
        self.assertFalse(SourceChange.objects.exists())
        page = self.client.get(sentences)
        self.assertContains(page, "Votre proposition en préparation")
        self.assertContains(page, "Phrase 2 scindée en 2")
        self.assertEqual(
            [sentence["text"] for sentence in page.context["sentences"]][1:3],
            ["Nous restons", "à la maison."],
        )
        response = self.client.post(
            self.url("source_sentence_edit", self.source.pk, 1),
            {"state": 0, "text": "Il pleut fort."},
        )
        self.assertContains(response, "Le texte a changé pendant que vous le modifiiez")

        proposal = SourceProposal.objects.get()
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(proposal.get_absolute_url()).status_code, 404)
        self.client.force_login(self.other)
        response = self.client.post(
            self.url("source_proposal_send", proposal.pk),
            {"explanation": "Des phrases plus courtes."},
        )
        self.assertRedirects(response, proposal.get_absolute_url())

        self.client.force_login(self.author)
        page = self.client.get(proposal.get_absolute_url())
        self.assertContains(page, "Adopter la proposition")
        self.assertContains(page, "Des phrases plus courtes.")
        listing = self.client.get(self.url("source_proposal_list", self.source.pk))
        self.assertContains(listing, "1 changement")
        response = self.client.post(
            self.url("source_proposal_act", proposal.pk, "adopter"), follow=True
        )
        self.assertContains(response, "La proposition est adoptée")
        self.assertEqual(self.source.segments.current().count(), 4)
        unknown = self.client.post(self.url("source_proposal_act", proposal.pk, "inconnu"))
        self.assertEqual(unknown.status_code, 404)
        self.client.force_login(self.other)
        refused = self.client.post(self.url("source_proposal_act", proposal.pk, "refuser"))
        self.assertEqual(refused.status_code, 403)
