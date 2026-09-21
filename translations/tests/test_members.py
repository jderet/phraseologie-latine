from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from translations import members
from translations.models import (
    ProjectMember,
    TranslatedSegment,
    TranslationProject,
    TranslationVersion,
    can_correct,
    is_editor,
    is_translator,
    is_version_writer,
)
from translations.permissions import can_challenge, can_edit, can_manage, can_translate
from translations.services import create_step, publish_version, save_translation

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class MemberTestCase(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version)

    def join(self, user=None, role=ProjectMember.Role.TRANSLATOR):
        """Someone takes a role in the project of the author."""
        user = user or self.other
        member = members.invite(self.project, self.author, user, role)
        members.answer(member, user, accept=True)
        return TranslationVersion.objects.get(pk=self.version.pk), member


class MemberServicesTests(MemberTestCase):
    def test_find_invitee_by_name_or_number(self):
        self.assertEqual(members.find_invitee("quintus"), self.other)
        self.assertEqual(members.find_invitee(str(self.other.pk)), self.other)
        with self.assertRaises(ValidationError):
            members.find_invitee("Nemo")

    def test_a_shared_name_asks_for_the_profile_number(self):
        make_user(email="twin@example.org", display_name="Quintus", role=CONTRIBUTOR)
        with self.assertRaises(ValidationError) as caught:
            members.find_invitee("Quintus")
        self.assertEqual(caught.exception.code, "ambiguous")

    def test_an_invitation_gives_no_access_until_accepted(self):
        member = members.invite(self.project, self.author, self.other)
        self.assertEqual(member.status, ProjectMember.Status.INVITED)
        self.assertFalse(is_version_writer(self.other, self.version))
        self.assertFalse(
            TranslationVersion.objects.visible_to(self.other).filter(pk=self.version.pk).exists()
        )

    def test_a_translator_writes_and_is_credited(self):
        version, _member = self.join()
        self.assertTrue(can_translate(self.other, version))
        self.assertFalse(can_manage(self.other, version))
        save_translation(version, self.first, "Pluit valde.", self.other)
        translated = TranslatedSegment.objects.get(version=version, segment=self.first)
        self.assertEqual(translated.written_by, self.other)
        # The author rewriting it takes it back.
        save_translation(version, self.first, "Pluit.", self.author)
        translated.refresh_from_db()
        self.assertIsNone(translated.written_by)

    def test_a_translator_creates_steps_but_does_not_publish(self):
        version, _member = self.join()
        step = create_step(version, self.other, "Premier jet")
        self.assertEqual(step.author, self.other)
        with self.assertRaises(PermissionDenied):
            publish_version(version, self.other)

    def test_an_editor_publishes_and_changes_the_project(self):
        version, _member = self.join(role=ProjectMember.Role.EDITOR)
        self.assertTrue(is_editor(self.other, self.project))
        self.assertTrue(can_edit(self.other, self.project))
        self.assertTrue(can_manage(self.other, version))
        publish_version(version, self.other)
        self.assertTrue(TranslationVersion.objects.get(pk=version.pk).is_published)

    def test_a_corrector_never_writes_the_translation(self):
        version, member = self.join(role=ProjectMember.Role.CORRECTOR)
        self.assertEqual(member.role, ProjectMember.Role.CORRECTOR)
        self.assertFalse(is_translator(self.other, self.project))
        self.assertFalse(can_translate(self.other, version))
        self.assertTrue(can_correct(self.other, self.project))
        with self.assertRaises(PermissionDenied):
            save_translation(version, self.first, "Pluit valde.", self.other)

    def test_correction_open_by_default_and_closed_by_an_editor(self):
        self.assertTrue(self.project.open_correction)
        self.assertTrue(can_correct(self.reviewer, self.project))
        self.project.open_correction = False
        self.project.save(update_fields=["open_correction"])
        self.assertFalse(can_correct(self.reviewer, self.project))
        self.assertTrue(can_correct(self.author, self.project))
        self.join(self.reviewer, role=ProjectMember.Role.CORRECTOR)
        project = TranslationProject.objects.get(pk=self.project.pk)
        self.assertTrue(can_correct(self.reviewer, project))

    def test_an_editor_closes_the_correction_from_the_project_page(self):
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("translations:project_edit", args=[self.project.pk]),
            {"title": self.project.title, "style": self.project.style, "description": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.project.refresh_from_db()
        self.assertFalse(self.project.open_correction)

    def test_a_translator_writes_the_latin_and_does_not_contest_it(self):
        version, _member = self.join()
        publish_version(version, self.author)
        version.refresh_from_db()
        self.assertFalse(can_challenge(self.other, version))
        save_translation(version, self.first, "Pluit multum.", self.other)
        self.assertEqual(
            TranslatedSegment.objects.get(version=version, segment=self.first).text,
            "Pluit multum.",
        )

    def test_only_an_editor_invites_and_changes_a_role(self):
        _version, member = self.join()
        with self.assertRaises(PermissionDenied):
            members.invite(self.project, self.other, self.reviewer)
        with self.assertRaises(PermissionDenied):
            members.change_role(member, self.other, ProjectMember.Role.EDITOR)
        members.change_role(member, self.author, ProjectMember.Role.EDITOR)
        member.refresh_from_db()
        self.assertEqual(member.role, ProjectMember.Role.EDITOR)

    def test_no_double_invitation(self):
        members.invite(self.project, self.author, self.other)
        with self.assertRaises(ValidationError):
            members.invite(self.project, self.author, self.other)

    def test_removed_member_loses_access_and_may_be_invited_again(self):
        version, member = self.join()
        members.remove(member, self.author)
        version = TranslationVersion.objects.get(pk=version.pk)
        self.assertFalse(can_translate(self.other, version))
        member = members.invite(self.project, self.author, self.other)
        self.assertEqual(member.status, ProjectMember.Status.INVITED)

    def test_a_member_may_leave(self):
        _version, member = self.join()
        members.remove(member, self.other)
        member.refresh_from_db()
        self.assertEqual(member.status, ProjectMember.Status.REMOVED)

    def test_only_the_invited_person_answers(self):
        member = members.invite(self.project, self.author, self.other)
        with self.assertRaises(PermissionDenied):
            members.answer(member, self.reviewer, accept=True)


class MemberPageTests(MemberTestCase):
    def test_an_editor_invites_from_the_page(self):
        self.client.force_login(self.author)
        url = reverse("translations:project_members", args=[self.project.pk])
        response = self.client.post(url, {"name": "Quintus", "role": "corrector"})
        self.assertRedirects(response, url)
        member = ProjectMember.objects.get(project=self.project, user=self.other)
        self.assertEqual(member.role, ProjectMember.Role.CORRECTOR)

    def test_invited_person_sees_the_invitation_but_not_the_draft(self):
        members.invite(self.project, self.author, self.other)
        self.client.force_login(self.other)
        page = self.client.get(reverse("translations:project_members", args=[self.project.pk]))
        self.assertContains(page, "Accepter")
        draft = self.client.get(reverse("translations:version", args=[self.version.pk]))
        self.assertEqual(draft.status_code, 404)

    def test_accepting_opens_the_project(self):
        member = members.invite(self.project, self.author, self.other)
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("translations:member_answer", args=[member.pk]), {"decision": "accept"}
        )
        self.assertRedirects(response, reverse("translations:project", args=[self.project.pk]))
        self.assertContains(
            self.client.get(reverse("translations:version", args=[self.version.pk])), "Pluit."
        )

    def test_the_role_is_changed_from_the_page(self):
        _version, member = self.join()
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("translations:member_role", args=[member.pk]), {"role": "editor"}
        )
        self.assertRedirects(
            response, reverse("translations:project_members", args=[self.project.pk])
        )
        member.refresh_from_db()
        self.assertEqual(member.role, ProjectMember.Role.EDITOR)

    def test_a_translator_may_not_invite_nor_publish(self):
        version, _member = self.join()
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("translations:project_members", args=[self.project.pk]),
            {"name": "Titus", "role": "translator"},
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse("translations:version_publish", args=[version.pk]))
        self.assertEqual(response.status_code, 403)

    def test_project_lists_the_draft_to_those_who_write_it(self):
        self.join()
        self.client.force_login(self.other)
        response = self.client.get(reverse("translations:project", args=[self.project.pk]))
        self.assertContains(response, reverse("translations:version", args=[self.version.pk]))

    def test_published_version_shows_those_who_write_it(self):
        version, _member = self.join()
        publish_version(version, self.author)
        response = self.client.get(reverse("translations:version", args=[version.pk]))
        self.assertContains(response, "Quintus")

    def test_draft_version_shows_nothing_to_strangers(self):
        self.join()
        response = self.client.get(reverse("translations:project", args=[self.project.pk]))
        self.assertNotContains(response, reverse("translations:version", args=[self.version.pk]))
