from django.core.exceptions import PermissionDenied
from django.urls import reverse

from api.serializers import version_summary
from moderation.services import hide_content
from translations.models import TranslationVersion
from translations.services import copy_version, create_step, publish_version, save_translation
from translations.steps import public_step, step_sentences

from .factories import make_project, make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class CopyTests(TranslationTestCase):
    """A variant starts from a public step of the main version, like a fork."""

    def setUp(self):
        self.source = make_published_version(self.author, self.project)
        # The working text of the source is not copied: only the text of the step.
        save_translation(self.source, self.first, "Imber.", self.author)
        self.step = self.source.steps.get()

    def copy(self, user=None, step=None):
        return copy_version(step or self.step, TranslationVersion(), user or self.other)

    def test_a_copy_is_an_open_variant_with_the_text_of_the_step(self):
        copy = self.copy()
        self.assertTrue(copy.is_draft)
        self.assertTrue(copy.is_open_variant)
        self.assertEqual(
            (copy.author, copy.project, copy.copied_from), (self.other, self.project, self.step)
        )
        texts = {item.segment_id: item for item in copy.segments.all()}
        self.assertEqual(texts[self.first.pk].text, "Pluit.")
        self.assertEqual({item.written_by for item in texts.values()}, {self.author})
        first_step = copy.steps.get()
        self.assertTrue(first_step.during_draft)
        self.assertEqual(first_step.message, "Variante partie de la traduction principale, étape 1")
        self.assertEqual(step_sentences(first_step)[self.second.pk].written_by, self.author)
        self.assertFalse(copy.segments.filter(justifications__isnull=False).exists())

    def test_rewriting_a_sentence_makes_it_ones_own(self):
        copy = self.copy()
        save_translation(copy, self.first, "Pluit.", self.other)
        self.assertEqual(copy.segments.get(segment=self.first).written_by, self.author)
        save_translation(copy, self.first, "Pluit hodie.", self.other)
        self.assertIsNone(copy.segments.get(segment=self.first).written_by)

    def test_copying_ones_own_version_credits_no_one_else(self):
        copy = self.copy(user=self.author)
        self.assertEqual({item.written_by for item in copy.segments.all()}, {None})

    def test_only_public_steps_of_the_main_version_are_copied(self):
        project = make_project(self.author, self.project.source_text, title="Autre projet")
        draft = make_version(self.author, project)
        self.assertEqual(draft, project.main_version)
        translate(draft)
        draft_step = create_step(draft, self.author, "Brouillon")
        with self.assertRaises(PermissionDenied):
            self.copy(step=draft_step)
        self.client.force_login(self.other)
        url = reverse("translations:version_copy", args=[draft.pk, 1])
        self.assertEqual(self.client.get(url).status_code, 404)
        publish_version(draft, self.author)
        self.assertEqual(self.client.get(url).status_code, 404)
        published_url = reverse("translations:version_copy", args=[draft.pk, 2])
        self.assertEqual(self.client.get(published_url).status_code, 200)
        # A variant, even published, is never copied.
        variant = make_published_version(self.reviewer, self.project)
        with self.assertRaises(PermissionDenied):
            self.copy(step=public_step(variant))
        variant_url = reverse("translations:version_copy", args=[variant.pk, 1])
        self.assertEqual(self.client.get(variant_url).status_code, 404)
        hide_content(self.source, self.reviewer)
        hidden_url = reverse("translations:version_copy", args=[self.source.pk, 1])
        self.assertEqual(self.client.get(hidden_url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(published_url).status_code, 302)

    def test_copy_from_the_pages(self):
        self.client.force_login(self.other)
        url = reverse("translations:version_copy", args=[self.source.pk, 1])
        self.assertContains(self.client.get(self.project.get_absolute_url()), url)
        self.assertContains(self.client.get(self.source.get_absolute_url()), url)
        self.assertContains(self.client.get(url), "Le style est celui du projet : cicéronien.")
        response = self.client.post(url)
        copy = TranslationVersion.objects.get(copied_from=self.step)
        self.assertRedirects(response, reverse("translations:version_edit", args=[copy.pk]))
        page = self.client.get(copy.get_absolute_url())
        self.assertContains(page, "Variante de Quintus")
        self.assertContains(page, "partie de la traduction principale, étape 1")
        self.assertContains(page, reverse("translations:propose_to_original", args=[copy.pk]))
        self.assertEqual(
            version_summary(copy, str)["copied_from"], {"version": self.source.pk, "step": 1}
        )
