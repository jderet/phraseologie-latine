from django.urls import reverse

from justifications.models import Justification
from translations.services import publish_version, save_translation

from .test_services import JustificationTestCase


class JustificationPagesTests(JustificationTestCase):
    def create_url(self, segment=None):
        return reverse("justifications:create", args=[self.version.pk, (segment or self.second).pk])

    def post_data(self, **fields):
        data = {
            "latin_excerpt": "manemus",
            "source_excerpt": "",
            "strength": "1",
            "comment": "",
            "references-TOTAL_FORMS": "2",
            "references-INITIAL_FORMS": "0",
            "references-MIN_NUM_FORMS": "0",
            "references-MAX_NUM_FORMS": "5",
        }
        return data | fields

    def test_the_search_offers_attestations(self):
        self.client.force_login(self.author)
        response = self.client.get(
            self.create_url(), {"extrait": "manemus", "debut": "5", "term1": "manemus"}
        )
        self.assertContains(response, f'value="{self.words[1].pk}" form="justification-form"')
        self.assertContains(response, 'value="manemus"')
        self.assertContains(response, 'name="debut" value="5"')

    def test_creation_with_an_attestation_and_a_reference(self):
        self.client.force_login(self.author)
        data = self.post_data(
            source_excerpt="restons",
            attestation=[f"{self.words[0].pk},{self.words[1].pk}"],
            **{"references-0-work": str(self.grammar.pk), "references-0-locator": "§ 426"},
        )
        response = self.client.post(self.create_url(), data)
        justification = Justification.objects.get()
        self.assertRedirects(response, justification.get_absolute_url())
        self.assertEqual(justification.evidences.count(), 2)
        page = self.client.get(justification.get_absolute_url())
        self.assertContains(page, "<mark>manemus</mark>")
        self.assertContains(page, "Cic. Off. 1, 1")
        self.assertContains(page, "A&amp;G")
        self.assertContains(page, "§ 426")
        self.assertContains(page, "restons")

    def test_errors_keep_the_chosen_attestations(self):
        self.client.force_login(self.author)
        value = str(self.words[1].pk)
        data = self.post_data(latin_excerpt="manebimus", attestation=[value])
        response = self.client.post(self.create_url(), data)
        self.assertContains(response, "Ce passage ne figure pas dans la phrase latine")
        self.assertContains(response, f'value="{value}" checked')
        response = self.client.post(self.create_url(), self.post_data(strength="2"))
        self.assertContains(response, "exige au moins une attestation du corpus")
        response = self.client.post(
            self.create_url(), self.post_data(strength="4", attestation=[value])
        )
        self.assertContains(response, "exige un commentaire")
        self.assertFalse(Justification.objects.exists())

    def test_an_untranslated_sentence_cannot_be_justified(self):
        save_translation(self.version, self.third, "", self.author)
        self.client.force_login(self.author)
        response = self.client.get(self.create_url(self.third))
        self.assertRedirects(response, reverse("translations:version_edit", args=[self.version.pk]))

    def test_drafts_stay_private_and_only_the_author_justifies(self):
        justification = self.justify()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.create_url()).status_code, 404)
        self.assertEqual(self.client.get(justification.get_absolute_url()).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(justification.get_absolute_url()).status_code, 404)

        publish_version(self.version, self.author)
        self.assertEqual(self.client.get(justification.get_absolute_url()).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.create_url()).status_code, 403)
        edit_url = reverse("justifications:edit", args=[justification.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 403)

    def test_version_page_and_editor_show_the_justifications(self):
        justification = self.justify()
        self.client.force_login(self.author)
        response = self.client.get(self.version.get_absolute_url())
        self.assertContains(response, justification.get_absolute_url())
        self.assertContains(response, self.create_url())
        editor = self.client.get(reverse("translations:version_edit", args=[self.version.pk]))
        self.assertContains(editor, 'class="button button-quiet justify-link"')
        self.assertContains(editor, justification.get_absolute_url())
        save_translation(self.version, self.second, "Domi manebimus.", self.author)
        self.assertContains(self.client.get(self.version.get_absolute_url()), "à revoir")

    def test_edit_add_and_withdraw_evidence(self):
        justification = self.justify()
        self.client.force_login(self.author)
        edit_url = reverse("justifications:edit", args=[justification.pk])
        data = {
            "latin_excerpt": "Domi manemus",
            "source_excerpt": "",
            "strength": "2",
            "comment": "",
        }
        self.assertRedirects(self.client.post(edit_url, data), justification.get_absolute_url())
        justification.refresh_from_db()
        self.assertEqual((justification.strength, justification.latin_start), (2, 0))

        add_url = reverse("justifications:evidence_add", args=[justification.pk])
        self.assertContains(self.client.post(add_url, self.post_data()), "Cochez une attestation")
        data = self.post_data(
            **{"references-0-work": str(self.grammar.pk), "references-0-locator": "§ 426"}
        )
        self.assertRedirects(self.client.post(add_url, data), justification.get_absolute_url())

        grammar = justification.evidences.get(kind="grammar")
        withdraw_url = reverse("justifications:evidence_withdraw", args=[grammar.pk])
        self.assertRedirects(self.client.post(withdraw_url), justification.get_absolute_url())
        attestation = justification.evidences.get(kind="corpus")
        withdraw_url = reverse("justifications:evidence_withdraw", args=[attestation.pk])
        response = self.client.post(withdraw_url, follow=True)
        self.assertContains(response, "exige au moins une attestation du corpus")
