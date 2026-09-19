from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from translations.editor import status_counts
from translations.models import TranslatedSegment
from translations.services import save_translation, set_sentence_status

from .factories import make_version, translate
from .test_versions import TranslationTestCase


class StatusTests(TranslationTestCase):
    def setUp(self):
        self.version = make_version(self.author, self.project)
        translate(self.version, ("Pluit.", "Domi manemus."))

    def status(self, segment):
        return TranslatedSegment.objects.get(version=self.version, segment=segment).status

    def test_a_new_sentence_is_a_draft_until_marked(self):
        self.assertEqual(self.status(self.first), "draft")
        set_sentence_status(self.version, self.first, "translated", self.author)
        self.assertEqual(self.status(self.first), "translated")

    def test_changing_the_latin_makes_a_draft_again(self):
        set_sentence_status(self.version, self.first, "reviewed", self.author)
        save_translation(self.version, self.first, "Pluit multum.", self.author)
        self.assertEqual(self.status(self.first), "draft")

    def test_an_empty_sentence_has_no_status(self):
        with self.assertRaises(ValidationError):
            set_sentence_status(self.version, self.third, "translated", self.author)

    def test_only_writers_set_a_status(self):
        with self.assertRaises(PermissionDenied):
            set_sentence_status(self.version, self.first, "translated", self.other)

    def test_status_is_recorded_in_the_history(self):
        revision = set_sentence_status(self.version, self.first, "translated", self.author)
        self.assertEqual(revision.comment, "traduite")
        self.assertIsNone(set_sentence_status(self.version, self.first, "translated", self.author))


class StatusPageTests(StatusTests):
    def test_json_endpoint(self):
        self.client.force_login(self.author)
        url = reverse("translations:sentence_status", args=[self.version.pk, self.first.pk])
        response = self.client.post(
            url, {"status": "reviewed"}, headers={"Accept": "application/json"}
        )
        self.assertEqual(response.json(), {"status": "reviewed"})

    def test_without_script_the_typed_latin_is_kept(self):
        self.client.force_login(self.author)
        url = reverse("translations:sentence_status", args=[self.version.pk, self.third.pk])
        response = self.client.post(
            url, {"status": "translated", f"s{self.third.pk}": "Cras proficiscemur."}
        )
        self.assertRedirects(
            response,
            reverse("translations:version_edit", args=[self.version.pk]) + f"#s{self.third.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(self.status(self.third), "translated")

    def test_editor_shows_the_bar_of_progress(self):
        self.client.force_login(self.author)
        response = self.client.get(reverse("translations:version_edit", args=[self.version.pk]))
        self.assertContains(response, 'class="status-bar"')
        self.assertContains(response, 'data-status="todo"')
        counts = {item["status"]: item["count"] for item in response.context["status_counts"]}
        self.assertEqual(counts, {"todo": 1, "draft": 2, "translated": 0, "reviewed": 0})

    def test_others_may_not_set_a_status(self):
        self.client.force_login(self.other)
        url = reverse("translations:sentence_status", args=[self.version.pk, self.first.pk])
        self.assertEqual(self.client.post(url, {"status": "translated"}).status_code, 404)

    def test_counts_are_shares_of_the_bar(self):
        rows = [{"data": {"status": "todo"}}, {"data": {"status": "reviewed"}}]
        items = status_counts(rows)
        self.assertEqual([item["width"] for item in items], ["50.000", "0.000", "0.000", "50.000"])
        self.assertEqual(items[3]["x"], "50.000")
