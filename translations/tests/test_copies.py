from django.core.exceptions import PermissionDenied
from django.urls import reverse

from api.serializers import version_summary
from moderation.services import hide_content
from translations.models import Style, TranslationVersion
from translations.services import copy_version, create_step, publish_version, save_translation
from translations.steps import step_sentences

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class CopyTests(TranslationTestCase):
    def setUp(self):
        self.source = make_published_version(self.other, self.project)
        # The working text of the source is not copied: only the text of the step.
        save_translation(self.source, self.first, "Imber.", self.other)
        self.step = self.source.steps.get()

    def copy(self, user=None, step=None):
        version = TranslationVersion(style=Style.TACITEAN)
        return copy_version(step or self.step, version, user or self.author)

    def test_a_copy_is_a_draft_with_the_text_of_the_step(self):
        copy = self.copy()
        self.assertTrue(copy.is_draft)
        self.assertEqual(
            (copy.author, copy.project, copy.copied_from), (self.author, self.project, self.step)
        )
        texts = {item.segment_id: item for item in copy.segments.all()}
        self.assertEqual(texts[self.first.pk].text, "Pluit.")
        self.assertEqual({item.written_by for item in texts.values()}, {self.other})
        first_step = copy.steps.get()
        self.assertTrue(first_step.during_draft)
        self.assertEqual(first_step.message, "Copie de la version de Quintus, étape 1")
        self.assertEqual(step_sentences(first_step)[self.second.pk].written_by, self.other)
        self.assertFalse(copy.segments.filter(justifications__isnull=False).exists())

    def test_rewriting_a_sentence_makes_it_ones_own(self):
        copy = self.copy()
        save_translation(copy, self.first, "Pluit.", self.author)
        self.assertEqual(copy.segments.get(segment=self.first).written_by, self.other)
        save_translation(copy, self.first, "Pluit hodie.", self.author)
        self.assertIsNone(copy.segments.get(segment=self.first).written_by)

    def test_copying_ones_own_version_credits_no_one_else(self):
        copy = self.copy(user=self.other)
        self.assertEqual({item.written_by for item in copy.segments.all()}, {None})

    def test_only_public_steps_are_copied(self):
        draft = make_version(self.other, self.project)
        translate(draft)
        draft_step = create_step(draft, self.other, "Brouillon")
        with self.assertRaises(PermissionDenied):
            self.copy(step=draft_step)
        self.client.force_login(self.author)
        url = reverse("translations:version_copy", args=[draft.pk, 1])
        self.assertEqual(self.client.get(url).status_code, 404)
        publish_version(draft, self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        published_url = reverse("translations:version_copy", args=[draft.pk, 2])
        self.assertEqual(self.client.get(published_url).status_code, 200)
        hide_content(self.source, self.reviewer)
        hidden_url = reverse("translations:version_copy", args=[self.source.pk, 1])
        self.assertEqual(self.client.get(hidden_url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(published_url).status_code, 302)

    def test_copy_from_the_pages(self):
        self.client.force_login(self.author)
        url = reverse("translations:version_copy", args=[self.source.pk, 1])
        self.assertContains(self.client.get(self.source.get_absolute_url()), url)
        self.assertContains(self.client.get(self.step.get_absolute_url()), url)
        form = self.client.get(url)
        self.assertEqual(form.context["form"].initial["style"], Style.CICERONIAN)
        response = self.client.post(url, {"style": Style.LIVIAN})
        copy = TranslationVersion.objects.get(copied_from=self.step)
        self.assertRedirects(response, reverse("translations:version_edit", args=[copy.pk]))
        self.assertEqual(copy.style, Style.LIVIAN)
        self.assertContains(
            self.client.get(copy.get_absolute_url()), "copiée de la version de Quintus, étape 1"
        )
        self.assertEqual(
            version_summary(copy, str)["copied_from"], {"version": self.source.pk, "step": 1}
        )
