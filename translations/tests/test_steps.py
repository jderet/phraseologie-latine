from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from api.serializers import version_data
from justifications.models import Challenge
from justifications.services import create_challenge
from moderation.models import Revision
from moderation.registry import uncounted_models
from moderation.services import hide_content
from translations.models import VersionStep
from translations.services import create_step, publish_version, save_translation
from translations.steps import pending_changes, public_step, shown_text, step_sentences

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class StepServicesTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version)

    def test_a_step_freezes_the_changed_sentences_with_a_message(self):
        self.assertEqual(len(pending_changes(self.version)), 3)
        first = create_step(self.version, self.author, "  Premier   jet ")
        self.assertEqual(
            (first.number, first.message, first.during_draft), (1, "Premier jet", True)
        )
        self.assertEqual(first.sentences.count(), 3)
        self.assertEqual(pending_changes(self.version), [])

        save_translation(self.version, self.second, "Domi maneamus.", self.author)
        [change] = pending_changes(self.version)
        self.assertEqual((change.before, change.after), ("Domi manemus.", "Domi maneamus."))
        second = create_step(self.version, self.author, "Subjonctif")
        self.assertEqual(second.number, 2)
        self.assertEqual([item.text for item in second.sentences.all()], ["Domi maneamus."])
        self.assertEqual(step_sentences(first)[self.second.pk].text, "Domi manemus.")
        frozen = step_sentences(second)
        self.assertEqual(frozen[self.second.pk].text, "Domi maneamus.")
        self.assertEqual(frozen[self.first.pk].step, first)
        self.assertEqual(Revision.objects.for_object(second).get().action, Revision.Action.CREATE)

    def test_an_erased_sentence_is_recorded_empty(self):
        create_step(self.version, self.author, "Premier jet")
        save_translation(self.version, self.third, "", self.author)
        step = create_step(self.version, self.author, "Sans la dernière phrase")
        self.assertEqual(step_sentences(step)[self.third.pk].text, "")

    def test_a_message_and_a_change_are_required(self):
        with self.assertRaises(ValidationError) as caught:
            create_step(self.version, self.author, " ")
        self.assertEqual(caught.exception.code, "no_message")
        create_step(self.version, self.author, "Premier jet")
        with self.assertRaises(ValidationError) as caught:
            create_step(self.version, self.author, "Encore")
        self.assertEqual(caught.exception.code, "unchanged")

    def test_only_the_author_creates_a_step(self):
        with self.assertRaises(PermissionDenied):
            create_step(self.version, self.other, "Intrus")
        self.assertFalse(VersionStep.objects.exists())

    def test_a_step_does_not_count_toward_the_limit_of_new_accounts(self):
        self.assertIn(VersionStep, uncounted_models())


class PublicStepTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)

    def test_publishing_creates_the_public_step(self):
        step = self.version.steps.get()
        self.assertEqual((step.number, step.message, step.during_draft), (1, "Publication", False))
        self.assertEqual(step.sentences.count(), 3)
        self.assertEqual(public_step(self.version), step)

    def test_the_public_sees_the_latest_step_and_the_author_the_working_text(self):
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        url = self.version.get_absolute_url()
        for user in (None, self.other, self.reviewer):
            with self.subTest(user=user and user.email):
                if user:
                    self.client.force_login(user)
                response = self.client.get(url)
                self.assertEqual(response.context["rows"][0]["saved"], "Pluit.")
                self.assertNotContains(response, "Imber")
        self.client.force_login(self.author)
        response = self.client.get(url)
        self.assertEqual(response.context["rows"][0]["saved"], "Imber cadit.")
        self.assertContains(response, "1 phrase a changé depuis la dernière étape")

        create_step(self.version, self.author, "Autre image")
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.context["rows"][0]["saved"], "Imber cadit.")
        self.assertContains(response, "Autre image")

    def test_the_working_text_stays_private_everywhere(self):
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        translated = self.version.segments.get(segment=self.first)
        self.assertEqual(shown_text(AnonymousUser(), translated), "Pluit.")
        self.assertEqual(shown_text(self.author, translated), "Imber cadit.")
        data = version_data(self.version, lambda path: path)
        self.assertEqual(data["segments"][0]["latin"], "Pluit.")
        self.assertEqual(data["step"]["number"], 1)
        urls = [
            self.project.get_absolute_url(),
            reverse("translations:project_compare", args=[self.project.pk]),
            reverse("translations:version_export_text", args=[self.version.pk]),
            reverse("translations:version_export_tei", args=[self.version.pk]),
            reverse("translations:version_export_tmx", args=[self.version.pk]),
            reverse("translations:version_export_print", args=[self.version.pk]),
            reverse("phraseology:units_in_sentence", args=[self.version.pk, self.first.pk]),
            reverse(
                "moderation:history", args=["translations", "translatedsegment", translated.pk]
            ),
        ]
        self.client.force_login(self.other)
        for url in urls:
            with self.subTest(url=url):
                self.assertNotIn("Imber", self.client.get(url).content.decode())

    def test_draft_steps_stay_private_after_publication(self):
        version = make_version(self.other, self.project)
        translate(version, ("Pluvia.",))
        draft_step = create_step(version, self.other, "Brouillon")
        publish_version(version, self.other)
        publication = version.steps.get(number=2)
        self.assertEqual(publication.sentences.count(), 0)
        self.assertEqual(public_step(version), publication)
        self.assertEqual(self.client.get(draft_step.get_absolute_url()).status_code, 404)
        response = self.client.get(publication.get_absolute_url())
        self.assertEqual(response.context["rows"][0]["saved"], "Pluvia.")
        history = self.client.get(reverse("translations:step_list", args=[version.pk]))
        self.assertEqual(history.context["steps"], [publication])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(draft_step.get_absolute_url()).status_code, 200)

    def test_a_step_keeps_its_text_at_a_fixed_address(self):
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        create_step(self.version, self.author, "Autre image")
        response = self.client.get(reverse("translations:step", args=[self.version.pk, 1]))
        self.assertEqual(response.context["rows"][0]["saved"], "Pluit.")
        self.assertFalse(response.context["is_current"])
        self.assertEqual(response.context["next_number"], 2)
        response = self.client.get(reverse("translations:step", args=[self.version.pk, 2]))
        self.assertEqual(response.context["rows"][0]["saved"], "Imber cadit.")
        self.assertTrue(response.context["is_current"])
        self.assertEqual(response.context["previous_number"], 1)
        missing = reverse("translations:step", args=[self.version.pk, 9])
        self.assertEqual(self.client.get(missing).status_code, 404)

    def test_a_hidden_step_leaves_the_public_on_the_previous_one(self):
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        second = create_step(self.version, self.author, "Autre image")
        hide_content(second, self.reviewer)
        self.assertEqual(public_step(self.version).number, 1)
        response = self.client.get(self.version.get_absolute_url())
        self.assertEqual(response.context["rows"][0]["saved"], "Pluit.")

    def test_a_challenge_is_about_the_public_step(self):
        save_translation(self.version, self.first, "Imber cadit.", self.author)
        translated = self.version.segments.get(segment=self.first)
        self.client.force_login(self.other)
        url = reverse("justifications:challenge_create", args=[translated.pk])
        self.assertEqual(self.client.get(url).context["latin"], "Pluit.")
        with self.assertRaises(ValidationError):
            create_challenge(
                Challenge(translated_segment=translated, latin_excerpt="Imber", argument="Non."),
                self.other,
                [],
            )
        challenge = create_challenge(
            Challenge(translated_segment=translated, latin_excerpt="Pluit", argument="Imber ?"),
            self.other,
            [],
        )
        self.assertEqual(challenge.step, public_step(self.version))
        response = self.client.get(challenge.get_absolute_url())
        self.assertEqual(response.context["latin"], "Pluit.")


class StepPagesTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        self.create_url = reverse("translations:step_create", args=[self.version.pk])
        self.client.force_login(self.author)

    def test_save_then_create_a_step_from_the_editor(self):
        edit = reverse("translations:version_edit", args=[self.version.pk])
        response = self.client.post(edit, {f"s{self.first.pk}": "Pluit.", "next": "step"})
        self.assertRedirects(response, self.create_url)
        page = self.client.get(self.create_url)
        self.assertEqual(len(page.context["changes"]), 1)
        self.assertContains(page, "<ins>Pluit.</ins>", html=True)

        response = self.client.post(self.create_url, {"message": "Première phrase"})
        step = self.version.steps.get()
        self.assertRedirects(response, step.get_absolute_url())
        self.assertContains(self.client.get(self.create_url), "Rien n’a changé")
        response = self.client.post(self.create_url, {"message": "Encore"})
        self.assertContains(response, "Rien n’a changé depuis la dernière étape.")
        self.assertEqual(self.version.steps.count(), 1)

    def test_only_the_author_creates_steps(self):
        translate(self.version)
        published = make_published_version(self.author, self.project)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.create_url).status_code, 404)
        other_url = reverse("translations:step_create", args=[published.pk])
        self.assertEqual(self.client.post(other_url, {"message": "Intrus"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(other_url).status_code, 302)
        self.assertEqual(published.steps.count(), 1)

    def test_draft_steps_are_private(self):
        translate(self.version)
        step = create_step(self.version, self.author, "Premier jet")
        history = reverse("translations:step_list", args=[self.version.pk])
        self.assertContains(self.client.get(history), "Premier jet")
        self.assertEqual(self.client.get(step.get_absolute_url()).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(step.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(history).status_code, 404)
