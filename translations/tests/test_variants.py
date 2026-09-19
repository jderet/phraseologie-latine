from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from activity.models import Notification, Verb
from translations import glossary, members, topics
from translations.models import (
    ChangeProposal,
    GlossaryEntry,
    Topic,
    TranslationVersion,
    is_maintainer,
)
from translations.permissions import can_propose, can_translate
from translations.services import (
    copy_version,
    create_proposal,
    decide_sentence,
    save_translation,
    set_aside_variant,
    withdraw_proposal,
)
from translations.steps import public_step

from .factories import make_project, make_published_version, make_source_text
from .test_versions import TranslationTestCase


class VariantTestCase(TranslationTestCase):
    """The author maintains the main version; Quintus writes a variant of it."""

    def setUp(self):
        self.main = make_published_version(self.author, self.project)
        self.variant = copy_version(public_step(self.main), TranslationVersion(), self.other)
        save_translation(self.variant, self.first, "Imber cadit.", self.other)
        save_translation(self.variant, self.second, "Domi nos manemus.", self.other)

    def send(self, variant=None, user=None):
        proposal = ChangeProposal(
            version=self.main, from_version=variant or self.variant, explanation="Plus vif."
        )
        return create_proposal(
            proposal,
            user or self.other,
            {self.first: "Imber cadit.", self.second: "Domi nos manemus."},
        )

    def refresh(self):
        self.variant.refresh_from_db()
        return self.variant


class VariantClosingTests(VariantTestCase):
    def test_a_variant_is_merged_once_a_sentence_is_accepted(self):
        proposal = self.send()
        first, second = proposal.sentences.all()
        decide_sentence(first, self.author, accept=True)
        self.assertTrue(self.refresh().is_open_variant)
        decide_sentence(second, self.author, accept=False)
        variant = self.refresh()
        self.assertEqual(variant.variant_status, TranslationVersion.VariantStatus.MERGED)
        self.assertIsNotNone(variant.closed_at)
        self.assertEqual(self.main.segments.get(segment=self.first).written_by, self.other)

    def test_a_variant_is_set_aside_when_every_sentence_is_refused(self):
        proposal = self.send()
        for proposed in proposal.sentences.all():
            decide_sentence(proposed, self.author, accept=False)
        self.assertEqual(self.refresh().variant_status, TranslationVersion.VariantStatus.SET_ASIDE)

    def test_a_closed_variant_is_no_longer_written(self):
        proposal = self.send()
        for proposed in proposal.sentences.all():
            decide_sentence(proposed, self.author, accept=True)
        variant = self.refresh()
        self.assertFalse(can_translate(self.other, variant))
        self.client.force_login(self.other)
        edit = reverse("translations:version_edit", args=[variant.pk])
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertContains(self.client.get(variant.get_absolute_url()), "Cette variante est close")

    def test_a_withdrawn_proposal_leaves_the_variant_open(self):
        withdraw_proposal(self.send(), self.other)
        self.assertTrue(self.refresh().is_open_variant)
        self.send()

    def test_one_open_proposal_per_variant_from_its_writers(self):
        self.send()
        with self.assertRaises(ValidationError):
            self.send()
        with self.assertRaises(PermissionDenied):
            self.send(user=self.reviewer)

    def test_a_proposal_from_a_variant_goes_to_the_main_version(self):
        other = make_published_version(self.reviewer, self.project)
        proposal = ChangeProposal(version=other, from_version=self.variant, explanation="?")
        with self.assertRaises(PermissionDenied):
            create_proposal(proposal, self.other, {self.first: "Imber cadit."})

    def test_the_page_sends_the_variant(self):
        self.client.force_login(self.other)
        url = reverse("translations:propose_to_original", args=[self.variant.pk])
        response = self.client.post(url, {"phrase": [self.first.pk], "explanation": "Vif."})
        proposal = self.main.proposals.get()
        self.assertRedirects(response, proposal.get_absolute_url())
        self.assertEqual(proposal.from_version, self.variant)
        page = self.client.get(self.variant.get_absolute_url())
        self.assertContains(page, "Votre proposition attend la décision des mainteneurs")


class SetAsideTests(VariantTestCase):
    def test_maintainers_set_a_variant_aside_with_a_reason(self):
        proposal = self.send()
        with self.assertRaises(PermissionDenied):
            set_aside_variant(self.variant, self.reviewer, "Non.")
        with self.assertRaises(ValidationError):
            set_aside_variant(self.variant, self.author, " ")
        set_aside_variant(self.variant, self.author, "Hors du style cicéronien.")
        variant = self.refresh()
        self.assertEqual(variant.variant_status, TranslationVersion.VariantStatus.SET_ASIDE)
        proposal.refresh_from_db()
        self.assertFalse(proposal.is_open)
        self.assertFalse(proposal.sentences.filter(decision="pending").exists())
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.other, event__verb=Verb.VARIANT_SET_ASIDE
            ).exists()
        )
        with self.assertRaises(PermissionDenied):
            set_aside_variant(self.variant, self.author, "Encore.")

    def test_a_co_author_of_the_main_version_is_a_maintainer(self):
        maintainer = make_user(email="m@example.org", role=CONTRIBUTOR, is_confirmed=True)
        self.assertFalse(is_maintainer(maintainer, self.project))
        member = members.invite(self.main, self.author, maintainer)
        members.answer(member, maintainer, accept=True)
        self.project.refresh_from_db()
        self.assertTrue(is_maintainer(maintainer, self.project))
        set_aside_variant(self.variant, maintainer, "Déjà traité.")
        self.assertTrue(self.refresh().is_closed)
        self.assertFalse(can_propose(self.reviewer, self.variant))

    def test_the_form_on_the_page_of_the_variant(self):
        url = reverse("translations:variant_set_aside", args=[self.variant.pk])
        self.client.force_login(self.other)
        self.client.post(url, {"reason": "Moi-même."})
        self.assertTrue(self.refresh().is_open_variant)
        # A draft variant stays private, even from the maintainers.
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(self.variant.get_absolute_url()).status_code, 404)
        self.variant.state = TranslationVersion.State.PUBLISHED
        self.variant.published_at = self.main.published_at
        self.variant.save()
        self.assertContains(self.client.get(self.variant.get_absolute_url()), url)
        response = self.client.post(url, {"reason": "Hors sujet."})
        self.assertRedirects(response, self.project.get_absolute_url())
        self.assertTrue(self.refresh().is_closed)


class MaintainerDecisionTests(VariantTestCase):
    def setUp(self):
        super().setUp()
        self.maintainer = make_user(email="m@example.org", role=CONTRIBUTOR, is_confirmed=True)
        member = members.invite(self.main, self.author, self.maintainer)
        members.answer(member, self.maintainer, accept=True)

    def test_maintainers_decide_on_the_glossary(self):
        entry = glossary.propose_term(
            GlossaryEntry(project=self.project, source_term="pluie", latin_term="imber"),
            self.other,
        )
        self.assertFalse(entry.is_adopted)
        self.assertTrue(glossary.can_decide_term(self.maintainer, self.project))
        glossary.decide_term(entry, self.maintainer, adopt=True)
        entry.refresh_from_db()
        self.assertTrue(entry.is_adopted)

    def test_maintainers_hear_of_and_close_topics(self):
        topic = topics.open_topic(Topic(project=self.project, title="Temps", body="?"), self.other)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.maintainer, event__verb=Verb.TOPIC_OPENED
            ).exists()
        )
        topics.set_topic_status(topic, self.maintainer, open_=False)
        topic.refresh_from_db()
        self.assertFalse(topic.is_open)


class TranslationPageTests(TestCase):
    """The page « Traduction » lists the texts, each with its projects."""

    @classmethod
    def setUpTestData(cls):
        cls.author = make_user(email="a@example.org", display_name="Marcus", role=CONTRIBUTOR)
        cls.other = make_user(email="o@example.org", display_name="Quintus", role=CONTRIBUTOR)
        cls.text = make_source_text(cls.author, title="La pluie")
        cls.lonely = make_source_text(cls.author, title="Un texte seul")
        cls.cicero = make_project(cls.author, cls.text, title="Pluvia Ciceroniana")
        make_published_version(cls.author, cls.cicero, texts=("Pluit.", "Domi manemus."))
        cls.draft = make_project(cls.other, cls.text, title="Pluvia in praeparatione")

    def test_texts_with_their_projects_and_progress(self):
        response = self.client.get(reverse("translations:source_list"))
        self.assertContains(response, "La pluie")
        self.assertContains(response, "Pluvia Ciceroniana")
        self.assertContains(response, "2 sur 3")
        self.assertContains(response, "en préparation")
        self.assertContains(response, "Aucune traduction pour l’instant.")
        self.assertNotContains(response, self.draft.main_version.get_absolute_url())

    def test_the_writers_see_the_progress_of_their_draft(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("translations:source_list"))
        self.assertContains(response, "0 sur 3 · brouillon")
        self.assertContains(response, reverse("translations:project_create", args=[self.lonely.pk]))

    def test_the_old_list_of_projects_leads_to_the_texts(self):
        response = self.client.get(reverse("translations:project_list"))
        self.assertRedirects(response, reverse("translations:source_list"), status_code=301)
