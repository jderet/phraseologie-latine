from django.core.exceptions import PermissionDenied
from django.urls import reverse

from accounts.tests.factories import make_user
from activity.models import Notification, Verb
from moderation.services import hide_content
from translations import topics
from translations.models import Topic

from .test_versions import TranslationTestCase


class TopicTestCase(TranslationTestCase):
    def open(self, author=None, **fields):
        fields.setdefault("title", "Le mot pluit")
        fields.setdefault("body", "Faut-il un sujet ?")
        topic = Topic(project=self.project, **fields)
        return topics.open_topic(topic, author or self.other)


class TopicServiceTests(TopicTestCase):
    def test_topics_are_numbered_within_their_project(self):
        self.assertEqual(self.open().number, 1)
        self.assertEqual(self.open().number, 2)

    def test_creator_of_the_project_is_told(self):
        self.open()
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.author, event__verb=Verb.TOPIC_OPENED
            ).exists()
        )

    def test_unknown_labels_are_dropped(self):
        topic = self.open(labels=["style", "pirate", "question"])
        self.assertEqual(topic.labels, ["question", "style"])

    def test_who_closes_and_reopens(self):
        topic = self.open()
        with self.assertRaises(PermissionDenied):
            topics.set_topic_status(topic, make_user(email="x@example.org"), open_=False)
        topics.set_topic_status(topic, self.author, open_=False)  # creator of the project
        topic.refresh_from_db()
        self.assertFalse(topic.is_open)
        self.assertEqual(topic.closed_by, self.author)
        topics.set_topic_status(topic, self.other, open_=True)  # its author
        topic.refresh_from_db()
        self.assertTrue(topic.is_open)

    def test_references_link_visible_topics_and_escape_the_rest(self):
        first = self.open()
        text = str(topics.linked_text(self.author, "Voir #1 et #9 <b>ici</b>\nfin", self.project))
        self.assertIn(f'<a href="{first.get_absolute_url()}"', text)
        self.assertIn("#9", text)
        self.assertIn("&lt;b&gt;", text)
        self.assertIn("<br>", text)


class TopicPageTests(TopicTestCase):
    def test_open_a_topic_about_a_sentence(self):
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("translations:topic_create", args=[self.project.pk]),
            {"title": "Temps", "body": "Présent ou futur ?", "labels": ["question"], "sentence": 2},
        )
        topic = Topic.objects.get()
        self.assertRedirects(response, topic.get_absolute_url())
        self.assertEqual(topic.segment, self.second)
        page = self.client.get(topic.get_absolute_url())
        self.assertContains(page, "Phrase 2")
        self.assertContains(page, "Nous restons à la maison.")

    def test_a_sentence_out_of_the_text_is_refused(self):
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("translations:topic_create", args=[self.project.pk]),
            {"title": "Temps", "body": "?", "sentence": 9},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Topic.objects.exists())

    def test_list_filters_by_state_and_label(self):
        self.open(title="Question ouverte", labels=["question"])
        closed = self.open(title="Erreur réglée", labels=["error"])
        topics.set_topic_status(closed, self.author, open_=False)
        url = reverse("translations:topic_list", args=[self.project.pk])
        response = self.client.get(url)
        self.assertContains(response, "Question ouverte")
        self.assertNotContains(response, "Erreur réglée")
        response = self.client.get(url + "?etat=fermes&etiquette=error")
        self.assertContains(response, "Erreur réglée")
        response = self.client.get(url + "?etiquette=style")
        self.assertNotContains(response, "Question ouverte")

    def test_tab_counts_open_topics(self):
        self.open()
        response = self.client.get(reverse("translations:project", args=[self.project.pk]))
        self.assertContains(response, reverse("translations:topic_list", args=[self.project.pk]))

    def test_hidden_topic_is_not_shown(self):
        topic = self.open()
        hide_content(topic, self.reviewer, "spam")
        response = self.client.get(topic.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_discussion_on_a_topic(self):
        topic = self.open()
        self.client.force_login(self.author)
        response = self.client.get(topic.get_absolute_url())
        self.assertContains(response, 'id="discussion"')
