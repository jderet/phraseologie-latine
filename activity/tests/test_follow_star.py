from django.urls import reverse

from activity.models import Star
from activity.services import is_following
from translations.tests.factories import (
    make_project,
    make_published_version,
    make_source_text,
    make_version,
)

from .test_notifications import ActivityTestCase


class FollowTests(ActivityTestCase):
    def follow_url(self, obj):
        return reverse("activity:follow", args=[obj._meta.app_label, obj._meta.model_name, obj.pk])

    def test_following_a_project_and_stopping(self):
        self.client.force_login(self.reader)
        response = self.client.post(self.follow_url(self.project))
        self.assertRedirects(response, self.project.get_absolute_url())
        self.assertTrue(is_following(self.reader, self.project))
        self.client.post(self.follow_url(self.project))
        self.assertFalse(is_following(self.reader, self.project))

    def test_creators_follow_what_they_create(self):
        self.assertTrue(is_following(self.author, self.project))
        self.assertTrue(is_following(self.author, self.source))

    def test_a_draft_of_someone_else_cannot_be_followed(self):
        version = make_version(self.author, self.project)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(self.follow_url(version)).status_code, 404)

    def test_only_followable_contents(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse("activity:follow", args=["moderation", "comment", 1]))
        self.assertEqual(response.status_code, 404)

    def test_button_on_the_project_page(self):
        self.client.force_login(self.reader)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, self.follow_url(self.project))


class StarTests(ActivityTestCase):
    def test_starring_a_published_version(self):
        version = make_published_version(self.author, self.project)
        self.client.force_login(self.reader)
        self.client.post(reverse("activity:star", args=[version.pk]))
        self.assertTrue(Star.objects.filter(user=self.reader, version=version).exists())
        page = self.client.get(version.get_absolute_url())
        self.assertContains(page, "Étoilée")
        self.client.post(reverse("activity:star", args=[version.pk]))
        self.assertFalse(Star.objects.filter(user=self.reader, version=version).exists())

    def test_a_draft_takes_no_star(self):
        version = make_version(self.author, self.project)
        self.client.force_login(self.author)
        self.client.post(reverse("activity:star", args=[version.pk]))
        self.assertFalse(Star.objects.exists())

    def test_texts_sorted_by_the_stars_of_their_translations(self):
        quiet_text = make_source_text(self.author, title="Texte calme")
        quiet = make_project(self.author, quiet_text, title="Projet calme")
        make_published_version(self.author, quiet)
        loved_text = make_source_text(self.author, title="Texte aimé")
        starred = make_project(self.author, loved_text, title="Projet aimé")
        version = make_published_version(self.author, starred)
        Star.objects.create(user=self.reader, version=version)
        response = self.client.get(reverse("translations:source_list") + "?tri=etoiles")
        titles = [text.title for text in response.context["page"]]
        self.assertLess(titles.index("Texte aimé"), titles.index("Texte calme"))
        self.assertContains(response, "1 étoile")

    def test_texts_sorted_by_activity(self):
        response = self.client.get(reverse("translations:source_list") + "?tri=activite")
        self.assertEqual(response.status_code, 200)
