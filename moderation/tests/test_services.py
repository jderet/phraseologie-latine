from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings

from accounts.limits import ContributionLimitReached
from moderation.models import Report, Revision
from moderation.registry import NotRegistered, can_revert, can_view
from moderation.services import (
    create_report,
    hide_content,
    resolve_report,
    revert_to,
    save_with_revision,
    unhide_content,
)

from .base import ModerationTestCase
from .models import ModerationTestNote


class SaveWithRevisionTests(ModerationTestCase):
    def test_creation_is_recorded(self):
        note = ModerationTestNote(author=self.owner, text="consilium capere")
        revision = save_with_revision(note, self.owner)
        self.assertEqual(revision.action, Revision.Action.CREATE)
        self.assertIsNone(revision.before)
        self.assertEqual(revision.after["text"], "consilium capere")
        self.assertEqual(revision.content_object, note)

    def test_change_keeps_the_previous_state(self):
        note = ModerationTestNote(author=self.owner, text="consilium capere")
        save_with_revision(note, self.owner)
        note.text = "consilium inire"
        revision = save_with_revision(note, self.owner, comment="plus rare")
        self.assertEqual(revision.action, Revision.Action.UPDATE)
        self.assertEqual(revision.before["text"], "consilium capere")
        self.assertEqual([change["name"] for change in revision.changes()], ["text"])

    def test_saving_without_change_records_nothing(self):
        note = ModerationTestNote(author=self.owner, text="bellum gerere")
        save_with_revision(note, self.owner)
        self.assertIsNone(save_with_revision(note, self.owner))
        self.assertEqual(Revision.objects.for_object(note).count(), 1)

    def test_unregistered_models_are_refused(self):
        with self.assertRaises(NotRegistered):
            save_with_revision(self.other, self.owner)


class NewAccountLimitTests(ModerationTestCase):
    @override_settings(NEW_ACCOUNT_DAILY_LIMIT=2)
    def test_new_accounts_have_a_daily_limit(self):
        for text in ("unus", "duo"):
            save_with_revision(ModerationTestNote(author=self.newcomer, text=text), self.newcomer)
        with self.assertRaises(ContributionLimitReached):
            save_with_revision(ModerationTestNote(author=self.newcomer, text="tres"), self.newcomer)

    @override_settings(NEW_ACCOUNT_DAILY_LIMIT=1)
    def test_confirmed_accounts_have_no_limit(self):
        for text in ("unus", "duo"):
            save_with_revision(ModerationTestNote(author=self.owner, text=text), self.owner)

    def test_new_accounts_cannot_post_links(self):
        note = ModerationTestNote(author=self.newcomer, text="voir https://example.org")
        with self.assertRaises(ValidationError):
            save_with_revision(note, self.newcomer)
        self.assertFalse(ModerationTestNote.objects.exists())

    def test_confirmed_accounts_can_post_links(self):
        note = ModerationTestNote(author=self.owner, text="voir https://example.org")
        self.assertIsNotNone(save_with_revision(note, self.owner))


class RevertTests(ModerationTestCase):
    def setUp(self):
        self.note = ModerationTestNote(author=self.owner, text="consilium capere")
        self.first = save_with_revision(self.note, self.owner)
        self.note.text = "consilium cepit"
        save_with_revision(self.note, self.owner)

    def test_reviewer_restores_a_previous_version(self):
        revision = revert_to(self.first, self.reviewer)
        self.note.refresh_from_db()
        self.assertEqual(self.note.text, "consilium capere")
        self.assertEqual(revision.action, Revision.Action.REVERT)
        self.assertEqual(revision.reverted_to, self.first)

    def test_owner_may_revert_but_not_other_contributors(self):
        with self.assertRaises(PermissionDenied):
            revert_to(self.first, self.other)
        self.assertIsNotNone(revert_to(self.first, self.owner))

    def test_reverting_to_the_current_state_records_nothing(self):
        revert_to(self.first, self.reviewer)
        self.assertIsNone(revert_to(self.first, self.reviewer))

    def test_revert_does_not_unhide(self):
        hide_content(self.note, self.reviewer)
        revert_to(self.first, self.reviewer)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_hidden)


class VisibilityTests(ModerationTestCase):
    def test_hidden_content_is_visible_to_reviewers_and_its_owner_only(self):
        note = ModerationTestNote.objects.create(author=self.owner, text="x")
        hide_content(note, self.reviewer)
        note.refresh_from_db()
        self.assertTrue(can_view(self.reviewer, note))
        self.assertTrue(can_view(self.owner, note))
        self.assertFalse(can_view(self.other, note))
        self.assertFalse(can_view(AnonymousUser(), note))

    def test_drafts_are_visible_to_their_author_only(self):
        draft = ModerationTestNote.objects.create(author=self.owner, text="x", is_draft=True)
        self.assertTrue(can_view(self.owner, draft))
        self.assertFalse(can_view(self.reviewer, draft))
        self.assertFalse(can_revert(self.reviewer, draft))

    def test_only_reviewers_hide_and_unhide(self):
        note = ModerationTestNote.objects.create(author=self.owner, text="x")
        with self.assertRaises(PermissionDenied):
            hide_content(note, self.owner)
        self.assertEqual(hide_content(note, self.reviewer).action, Revision.Action.HIDE)
        self.assertEqual(unhide_content(note, self.reviewer).action, Revision.Action.UNHIDE)


class ReportTests(ModerationTestCase):
    def setUp(self):
        self.note = ModerationTestNote.objects.create(author=self.owner, text="x")

    def test_one_open_report_per_person(self):
        report, created = create_report(self.other, self.note, Report.Reason.SPAM)
        self.assertTrue(created)
        again, created = create_report(self.other, self.note, Report.Reason.SPAM)
        self.assertFalse(created)
        self.assertEqual(again, report)

    def test_cannot_report_what_one_cannot_see(self):
        draft = ModerationTestNote.objects.create(author=self.owner, text="x", is_draft=True)
        with self.assertRaises(PermissionDenied):
            create_report(self.other, draft, Report.Reason.SPAM)

    def test_reviewer_handles_a_report_and_hides_the_content(self):
        report, _created = create_report(self.other, self.note, Report.Reason.ILLEGAL)
        resolve_report(report, self.reviewer, Report.Status.HANDLED, "retiré", hide=True)
        report.refresh_from_db()
        self.note.refresh_from_db()
        self.assertEqual(report.status, Report.Status.HANDLED)
        self.assertEqual(report.handled_by, self.reviewer)
        self.assertIsNotNone(report.handled_at)
        self.assertTrue(self.note.is_hidden)

    def test_contributors_cannot_handle_reports(self):
        report, _created = create_report(self.other, self.note, Report.Reason.SPAM)
        with self.assertRaises(PermissionDenied):
            resolve_report(report, self.owner, Report.Status.REJECTED)
