from django.urls import reverse

from api.serializers import version_data
from moderation.registry import can_view
from translations.services import create_step, publish_version, save_translation
from translations.steps import public_step

from .test_services import JustificationTestCase


class JustificationStepTests(JustificationTestCase):
    def test_a_justification_comes_out_with_the_next_step(self):
        publish_version(self.version, self.author)
        justification = self.justify()
        self.assertIsNone(justification.step)
        detail = justification.get_absolute_url()
        version_url = self.version.get_absolute_url()
        self.assertFalse(can_view(self.other, justification.evidences.get()))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.get(version_url).context["rows"][1]["justifications"], [])
        self.assertEqual(version_data(self.version, str)["justifications"], [])
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertContains(
            self.client.get(version_url), "1 justification paraîtra à la prochaine étape"
        )

        step = create_step(self.version, self.author, "Justification de manemus")
        justification.refresh_from_db()
        self.assertEqual(justification.step, step)
        self.assertEqual(step.sentences.count(), 0)
        self.assertTrue(can_view(self.other, justification.evidences.get()))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail).status_code, 200)
        rows = self.client.get(version_url).context["rows"]
        self.assertEqual(rows[1]["justifications"], [justification])
        self.assertEqual(len(version_data(self.version, str)["justifications"]), 1)
        earlier = self.client.get(reverse("translations:step", args=[self.version.pk, 1]))
        self.assertEqual(earlier.context["rows"][1]["justifications"], [])

    def test_waiting_justifications_are_enough_for_a_step(self):
        create_step(self.version, self.author, "Premier jet")
        self.justify()
        self.client.force_login(self.author)
        page = self.client.get(reverse("translations:step_create", args=[self.version.pk]))
        self.assertContains(page, "Justifications qui paraîtront avec cette étape")
        self.assertEqual(create_step(self.version, self.author, "Justification").number, 2)

    def test_publication_brings_out_the_draft_justifications(self):
        justification = self.justify()
        publish_version(self.version, self.author)
        justification.refresh_from_db()
        self.assertEqual(justification.step, public_step(self.version))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(justification.get_absolute_url()).status_code, 200)

    def test_the_author_chooses_to_show_the_draft_steps(self):
        create_step(self.version, self.author, "Premier jet")
        save_translation(self.version, self.first, "Pluit hodie.", self.author)
        url = reverse("translations:version_publish", args=[self.version.pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "Votre brouillon compte 1 étape.")
        response = self.client.post(
            url, {"message": "Première publication", "show_draft_steps": "on"}
        )
        self.assertRedirects(response, self.version.get_absolute_url())
        self.version.refresh_from_db()
        self.assertTrue(self.version.shows_draft_steps)
        draft_step, publication = self.version.steps.all()
        self.assertEqual(publication.message, "Première publication")
        self.assertEqual(publication.sentences.count(), 1)
        self.client.force_login(self.other)
        history = self.client.get(reverse("translations:step_list", args=[self.version.pk]))
        self.assertEqual(history.context["steps"], [publication, draft_step])
        self.assertEqual(self.client.get(draft_step.get_absolute_url()).status_code, 200)
