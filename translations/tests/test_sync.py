from django.urls import reverse

from translations.models import TranslatedSegment, TranslationVersion
from translations.services import copy_version, create_step, save_translation
from translations.steps import public_step
from translations.sync import take_upstream, upstream_changes

from .factories import make_published_version
from .test_versions import TranslationTestCase


class SyncTests(TranslationTestCase):
    def setUp(self):
        self.original = make_published_version(self.author, self.project)
        self.copy = copy_version(
            public_step(self.original),
            TranslationVersion(),
            self.other,
        )
        save_translation(self.original, self.first, "Imber cadit.", self.author)
        save_translation(self.original, self.second, "Domi mansimus.", self.author)
        create_step(self.original, self.author, "Retouches")
        # The copy changed the second sentence on its own.
        save_translation(self.copy, self.second, "Domi nos manemus.", self.other)

    def text(self, segment):
        return TranslatedSegment.objects.get(version=self.copy, segment=segment).text

    def test_changes_of_the_original_since_the_copy(self):
        latest, changes = upstream_changes(self.other, self.copy)
        self.assertEqual(latest.number, 2)
        self.assertEqual([change.after for change in changes], ["Imber cadit.", "Domi mansimus."])
        self.assertEqual([change.is_clean for change in changes], [True, False])

    def test_take_the_chosen_ones_in_the_name_of_their_writer(self):
        taken = take_upstream(self.other, self.copy, {self.first.pk})
        self.assertEqual(taken, 1)
        self.assertEqual(self.text(self.first), "Imber cadit.")
        self.assertEqual(self.text(self.second), "Domi nos manemus.")
        translated = TranslatedSegment.objects.get(version=self.copy, segment=self.first)
        self.assertEqual(translated.written_by, self.author)
        # Up to date: nothing more to take.
        self.copy.refresh_from_db()
        self.assertEqual(upstream_changes(self.other, self.copy)[1], [])

    def test_page(self):
        self.client.force_login(self.other)
        url = reverse("translations:sync_copy", args=[self.copy.pk])
        self.assertContains(self.client.get(url), "vous l’avez aussi modifiée")
        response = self.client.post(url, {"phrase": [self.first.pk]})
        self.assertRedirects(response, reverse("translations:version_edit", args=[self.copy.pk]))

    def test_only_writers_of_the_copy(self):
        self.client.force_login(self.reviewer)
        url = reverse("translations:sync_copy", args=[self.copy.pk])
        self.assertEqual(self.client.get(url).status_code, 404)


class ProposeToOriginalTests(SyncTests):
    def test_differences_become_a_proposal(self):
        self.client.force_login(self.other)
        url = reverse("translations:propose_to_original", args=[self.copy.pk])
        page = self.client.get(url)
        self.assertEqual(len(page.context["rows"]), 1)
        response = self.client.post(
            url, {"phrase": [self.second.pk], "explanation": "Le pronom insiste."}
        )
        proposal = self.original.proposals.get()
        self.assertRedirects(response, proposal.get_absolute_url())
        self.assertEqual(proposal.author, self.other)
        self.assertEqual(proposal.sentences.get().text, "Domi nos manemus.")
