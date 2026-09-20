from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from api.serializers import version_data
from justifications.models import Justification
from justifications.services import update_justification
from justifications.tests.test_services import JustificationTestCase
from moderation.models import Revision
from moderation.services import revert_to
from translations.models import (
    ChangeProposal,
    Segment,
    SourceChange,
    SourceText,
    TranslationVersion,
)
from translations.segmentation import MAX_SENTENCES
from translations.services import (
    change_source_text,
    copy_version,
    create_proposal,
    create_step,
    decide_sentence,
    save_translation,
)
from translations.sources import SourceHistory
from translations.steps import pending_changes, step_sentences

from .factories import SENTENCES, make_published_version
from .test_versions import TranslationTestCase


def insert(before, *texts, paragraph=False):
    sentences = [
        {"text": text, "starts_paragraph": paragraph and index == 0}
        for index, text in enumerate(texts)
    ]
    return {"kind": "insert", "before": before, "sentences": sentences}


def edit(index, text, paragraph=None):
    return {"kind": "edit", "index": index, "text": text, "starts_paragraph": paragraph}


def merge(index):
    return {"kind": "merge", "index": index}


def split(index, *parts):
    return {"kind": "split", "index": index, "parts": list(parts)}


class SourceChangeTests(TranslationTestCase):
    def current(self):
        return list(self.source.segments.current().values_list("order", "text"))

    def assertRefused(self, operation, code, user=None):
        with self.assertRaises(ValidationError) as caught:
            change_source_text(self.source, operation, user or self.author)
        self.assertEqual(caught.exception.code, code)

    def test_sentences_are_added_at_the_start_between_and_at_the_end(self):
        change_source_text(self.source, insert(0, "Au début."), self.author)
        change_source_text(self.source, insert(2, "Entre deux.", "  Encore. "), self.author)
        change = change_source_text(self.source, insert(6, "À la fin."), self.author)
        self.assertEqual(
            self.current(),
            [
                (1, "Au début."),
                (2, "Il pleut."),
                (3, "Entre deux."),
                (4, "Encore."),
                (5, "Nous restons à la maison."),
                (6, "Demain, nous partirons."),
                (7, "À la fin."),
            ],
        )
        self.assertEqual((change.number, change.kind, change.author), (3, "insert", self.author))
        source = SourceText.objects.get(pk=self.source.pk)
        self.assertEqual(source.state, 3)
        self.assertTrue(source.text.startswith("Au début.\n\nIl pleut.\nEntre deux.\n"))
        revision = Revision.objects.for_object(source).order_by("-pk").first()
        self.assertEqual(revision.comment, "1 phrase ajoutée à la fin")

    def test_an_edit_replaces_the_sentence_and_keeps_the_old_one(self):
        change_source_text(self.source, edit(1, "Nous restons chez nous."), self.author)
        self.second.refresh_from_db()
        self.assertEqual((self.second.removed_in, self.second.order), (1, None))
        self.assertEqual(self.current()[1], (2, "Nous restons chez nous."))
        self.assertEqual(self.second.latest.text, "Nous restons chez nous.")
        history = SourceHistory(SourceText.objects.get(pk=self.source.pk))
        self.assertEqual([segment.text for segment in history.segments_at(0)], list(SENTENCES))
        self.assertRefused(edit(1, "Nous restons chez nous."), "unchanged")
        self.assertRefused(edit(1, " "), "empty")
        self.assertRefused(edit(3, "Hors du texte."), "missing")

    def test_sentences_are_merged_and_split_without_changing_a_word(self):
        change_source_text(self.source, merge(0), self.author)
        self.assertEqual(
            self.current(),
            [(1, "Il pleut. Nous restons à la maison."), (2, "Demain, nous partirons.")],
        )
        change_source_text(
            self.source, split(0, "Il pleut.", "Nous restons à la maison."), self.author
        )
        self.assertEqual(self.current()[:2], [(1, "Il pleut."), (2, "Nous restons à la maison.")])
        paragraphs = list(self.source.segments.current().values_list("starts_paragraph", flat=True))
        self.assertEqual(paragraphs, [True, False, False])
        self.assertRefused(split(0, "Il pleure."), "one_part")
        self.assertRefused(split(0, "Il", "pleure."), "split_changed")
        self.assertRefused(merge(2), "missing")
        self.assertEqual(Segment.objects.filter(source_text=self.source).count(), 6)

    def test_only_whoever_added_the_text_and_reviewers_change_its_sentences(self):
        with self.assertRaises(PermissionDenied):
            change_source_text(self.source, merge(0), self.other)
        change_source_text(self.source, merge(0), self.reviewer)
        self.assertEqual(SourceChange.objects.get().author, self.reviewer)

    def test_a_text_keeps_within_the_limits(self):
        self.assertRefused(insert(3, *["Encore une phrase."] * MAX_SENTENCES), "too_long")
        self.assertRefused(insert(3, "a" * 2001), "sentence_too_long")
        self.assertFalse(SourceChange.objects.exists())

    def test_a_revert_leaves_the_sentences_alone(self):
        change_source_text(self.source, edit(0, "Il pleut fort."), self.author)
        creation = Revision.objects.for_object(self.source).order_by("pk").first()
        revert_to(creation, self.reviewer)
        source = SourceText.objects.get(pk=self.source.pk)
        self.assertEqual(source.state, 1)
        self.assertTrue(source.text.startswith("Il pleut fort."))


class LatinFollowsTheSourceTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)

    def fresh_version(self):
        return TranslationVersion.objects.get(pk=self.version.pk)

    def working(self):
        return list(
            self.version.segments.current()
            .order_by("segment__position")
            .values_list("segment__text", "text", "written_by")
        )

    def shown(self, url, user=None):
        if user:
            self.client.force_login(user)
        else:
            self.client.logout()
        rows = self.client.get(url).context["rows"]
        return [(row["number"], row["segment"].text, row["saved"]) for row in rows]

    def test_the_latin_is_carried_and_the_public_keeps_the_text_of_the_step(self):
        change_source_text(self.source, merge(0), self.author)
        self.assertEqual(
            self.working(),
            [
                ("Il pleut. Nous restons à la maison.", "Pluit. Domi manemus.", None),
                ("Demain, nous partirons.", "Cras proficiscemur.", None),
            ],
        )
        self.assertEqual(pending_changes(self.fresh_version()), [])
        url = self.version.get_absolute_url()
        public = [
            (1, "Il pleut.", "Pluit."),
            (2, "Nous restons à la maison.", "Domi manemus."),
            (3, "Demain, nous partirons.", "Cras proficiscemur."),
        ]
        self.assertEqual(self.shown(url), public)
        self.assertEqual(len(version_data(self.fresh_version(), str)["segments"]), 3)
        self.assertEqual(len(self.shown(url, self.author)), 2)

        # Only the source text changed: the step is allowed, and the public now sees it.
        step = create_step(self.fresh_version(), self.author, "Deux phrases fusionnées")
        self.assertEqual(step.source_state, 1)
        merged = self.source.segments.current().first()
        self.assertEqual(step_sentences(step)[merged.pk].text, "Pluit. Domi manemus.")
        self.assertEqual(
            self.shown(url),
            [
                (1, "Il pleut. Nous restons à la maison.", "Pluit. Domi manemus."),
                (2, "Demain, nous partirons.", "Cras proficiscemur."),
            ],
        )
        self.assertEqual(
            self.shown(reverse("translations:step", args=[self.version.pk, 1])), public
        )
        with self.assertRaises(ValidationError):
            create_step(self.fresh_version(), self.author, "Encore")

    def test_a_split_leaves_the_latin_on_its_first_part(self):
        change_source_text(self.source, split(1, "Nous restons", "à la maison."), self.author)
        self.assertEqual(
            self.working(),
            [
                ("Il pleut.", "Pluit.", None),
                ("Nous restons", "Domi manemus.", None),
                ("Demain, nous partirons.", "Cras proficiscemur.", None),
            ],
        )

    def test_a_merge_keeps_a_shared_writer_else_credits_the_author(self):
        save_translation(self.version, self.first, "Imber.", self.author, written_by=self.other)
        save_translation(self.version, self.second, "Domi.", self.author, written_by=self.other)
        change_source_text(self.source, merge(0), self.author)
        self.assertEqual(self.working()[0][1:], ("Imber. Domi.", self.other.pk))
        change_source_text(self.source, merge(0), self.author)
        self.assertEqual(self.working()[0][1:], ("Imber. Domi. Cras proficiscemur.", None))

    def test_a_copy_of_an_earlier_step_follows_the_current_text(self):
        change_source_text(self.source, merge(1), self.author)
        copy = copy_version(self.version.steps.get(), TranslationVersion(), self.other)
        self.assertEqual(
            list(copy.segments.values_list("segment__text", "text", "written_by")),
            [
                ("Il pleut.", "Pluit.", self.author.pk),
                (
                    "Nous restons à la maison. Demain, nous partirons.",
                    "Domi manemus. Cras proficiscemur.",
                    self.author.pk,
                ),
            ],
        )
        self.assertEqual(copy.steps.get().source_state, 1)

    def test_the_comparison_of_two_steps_carries_the_latin(self):
        change_source_text(self.source, insert(0, "D’abord."), self.author)
        first = self.source.segments.current().first()
        save_translation(self.version, first, "Primum.", self.author)
        create_step(self.fresh_version(), self.author, "Début")
        self.client.logout()
        url = reverse("translations:step_compare", args=[self.version.pk])
        rows = self.client.get(url, {"de": 1, "a": 2}).context["rows"]
        self.assertEqual([(row["number"], row["after"]) for row in rows], [(1, "Primum.")])
        # Steps asked in the wrong order are swapped.
        rows = self.client.get(url, {"de": 2, "a": 1}).context["rows"]
        self.assertEqual([(row["number"], row["after"]) for row in rows], [(1, "Primum.")])

    def test_a_removed_sentence_takes_no_latin(self):
        proposal = create_proposal(
            ChangeProposal(version=self.version, explanation="Subjonctif."),
            self.other,
            {self.second: "Domi maneamus."},
        )
        change_source_text(self.source, edit(1, "Nous restons chez nous."), self.author)
        with self.assertRaises(ValueError):
            save_translation(self.fresh_version(), self.second, "Domi.", self.author)
        proposed = proposal.sentences.get()
        with self.assertRaises(ValidationError) as caught:
            decide_sentence(proposed, self.author, accept=True)
        self.assertEqual(caught.exception.code, "source_changed")
        self.client.force_login(self.author)
        page = self.client.get(proposal.get_absolute_url())
        self.assertContains(page, "La phrase source a changé depuis cette proposition")
        self.assertEqual(page.context["sentences"][0]["number"], 2)
        decide_sentence(proposed, self.author, accept=False)


class JustificationsFollowTheSourceTests(JustificationTestCase):
    def test_a_justification_follows_the_sentence_that_carries_its_latin(self):
        justification = self.justify()
        create_step(self.version, self.author, "Premier jet")
        change_source_text(self.source, merge(0), self.author)

        self.client.force_login(self.author)
        rows = self.client.get(self.version.get_absolute_url()).context["rows"]
        self.assertEqual(rows[0]["justifications"], [justification])
        self.assertEqual(rows[0]["justifications"][0].shown_text, "Pluit. Domi manemus.")
        step_url = reverse("translations:step", args=[self.version.pk, 1])
        rows = self.client.get(step_url).context["rows"]
        self.assertEqual(rows[1]["justifications"], [justification])

        justification = Justification.objects.get(pk=justification.pk)
        update_justification(justification, self.author)
        self.assertEqual(Justification.objects.get(pk=justification.pk).latin_start, 12)
