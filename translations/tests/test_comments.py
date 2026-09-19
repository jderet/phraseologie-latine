from django.core.exceptions import PermissionDenied
from django.urls import reverse

from activity.models import Notification, Verb
from translations.comments import comments_for, open_counts, post_sentence_comment, set_resolved

from .factories import make_published_version, make_version, translate
from .test_versions import TranslationTestCase


class CommentTests(TranslationTestCase):
    def test_a_draft_is_commented_by_its_writers_only(self):
        draft = make_version(self.author, self.project)
        translate(draft)
        comment = post_sentence_comment(draft, self.first, self.author, "À revoir.")
        with self.assertRaises(PermissionDenied):
            post_sentence_comment(draft, self.first, self.other, "Je passe.")
        self.assertEqual(comments_for(self.other, draft), [])
        self.assertEqual(comments_for(self.author, draft), [comment])

    def test_a_published_version_is_commented_by_all_and_writers_are_told(self):
        version = make_published_version(self.author, self.project)
        post_sentence_comment(version, self.first, self.other, "Pourquoi pluit ?")
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.author, event__verb=Verb.SENTENCE_COMMENTED
            ).exists()
        )
        self.assertEqual(len(comments_for(self.reviewer, version)), 1)

    def test_resolving(self):
        version = make_published_version(self.author, self.project)
        comment = post_sentence_comment(version, self.first, self.other, "Pourquoi ?")
        self.assertEqual(open_counts(self.author, version), {self.first.pk: 1})
        with self.assertRaises(PermissionDenied):
            set_resolved(comment, self.reviewer, True)
        set_resolved(comment, self.author, True)
        self.assertEqual(open_counts(self.author, version), {})

    def test_panel_post_and_page(self):
        version = make_published_version(self.author, self.project)
        self.client.force_login(self.other)
        url = reverse("translations:comment_post", args=[version.pk, self.first.pk])
        response = self.client.post(
            url, {"text": "Bien vu."}, headers={"Accept": "application/json"}
        )
        self.assertEqual(response.json(), {"ok": True})
        panel = self.client.get(
            reverse("translations:editor_comments", args=[version.pk, self.first.pk])
        )
        self.assertContains(panel, "Bien vu.")
        page = self.client.get(reverse("translations:version_comments", args=[version.pk]))
        self.assertContains(page, "Bien vu.")
        self.assertContains(page, "Phrase 1")

    def test_editor_shows_the_count_and_filters(self):
        version = make_version(self.author, self.project)
        translate(version)
        post_sentence_comment(version, self.second, self.author, "Temps ?")
        self.client.force_login(self.author)
        url = reverse("translations:version_edit", args=[version.pk])
        response = self.client.get(url, {"filtre": "commentees"})
        self.assertEqual([row["number"] for row in response.context["shown_rows"]], [2])
        self.assertContains(response, 'class="comment-badge"')

    def test_comment_from_the_public_page(self):
        version = make_published_version(self.author, self.project)
        self.client.force_login(self.other)
        page = self.client.get(reverse("translations:version", args=[version.pk]))
        self.assertContains(page, "?phrase=2#commenter")
        response = self.client.post(
            reverse("translations:comment_post_by_number", args=[version.pk]),
            {"phrase": "2", "text": "Et domi ?"},
        )
        self.assertEqual(response.status_code, 302)
        comment = comments_for(self.author, version)[0]
        self.assertEqual(comment.segment, self.second)
