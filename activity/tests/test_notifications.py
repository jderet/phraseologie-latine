from django.test import TestCase
from django.urls import reverse

from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.services import anonymize_user
from accounts.tests.factories import make_user
from activity.models import Notification, Star, Subscription, Verb
from activity.services import follow, mentioned_users, star, unfollow, unread_count
from moderation.services import post_comment
from translations import members
from translations.models import Topic
from translations.services import create_step, publish_version, save_translation
from translations.tests.factories import (
    make_project,
    make_published_version,
    make_source_text,
    make_version,
    translate,
)
from translations.topics import open_topic


class ActivityTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = make_user(
            email="author@example.org", display_name="Marcus", role=CONTRIBUTOR, is_confirmed=True
        )
        cls.other = make_user(
            email="other@example.org",
            display_name="Quintus Ennius",
            role=CONTRIBUTOR,
            is_confirmed=True,
        )
        cls.reader = make_user(email="reader@example.org", display_name="Titus", role=REVIEWER)
        cls.source = make_source_text(cls.author)
        cls.first = cls.source.segments.first()
        cls.project = make_project(cls.author, cls.source)

    def open_topic(self):
        """A topic opened by someone else in the project of the author."""
        return open_topic(Topic(project=self.project, title="Style", body="Mieux ?"), self.other)

    def verbs(self, user):
        return list(
            Notification.objects.filter(recipient=user).values_list("event__verb", flat=True)
        )


class NotificationTests(ActivityTestCase):
    def test_a_topic_is_told_to_the_writers_of_the_translation(self):
        self.open_topic()
        self.assertIn(Verb.TOPIC_OPENED, self.verbs(self.author))
        self.assertNotIn(Verb.TOPIC_OPENED, self.verbs(self.other))

    def test_followers_of_a_project_hear_of_a_publication_not_of_a_draft(self):
        follow(self.reader, self.project)
        version = make_version(self.author, self.project)
        translate(version)
        create_step(version, self.author, "Premier jet")
        self.assertEqual(self.verbs(self.reader), [])
        publish_version(version, self.author)
        self.assertIn(Verb.VERSION_PUBLISHED, self.verbs(self.reader))

    def test_co_authors_hear_of_draft_steps(self):
        version = make_version(self.author, self.project)
        member = members.invite(self.project, self.author, self.other)
        self.assertEqual(self.verbs(self.other), [Verb.MEMBER_INVITED])
        members.answer(member, self.other, accept=True)
        self.assertIn(Verb.MEMBER_JOINED, self.verbs(self.author))
        save_translation(version, self.first, "Pluit.", self.author)
        create_step(version, self.author, "Premier jet")
        self.assertIn(Verb.STEP_CREATED, self.verbs(self.other))

    def test_unfollowing_a_project_silences_it(self):
        unfollow(self.author, self.project)
        self.open_topic()
        # The writers of the translation are always told of a topic.
        self.assertIn(Verb.TOPIC_OPENED, self.verbs(self.author))

    def test_a_message_tells_the_discussion_and_the_people_mentioned(self):
        topic = self.open_topic()
        Notification.objects.all().delete()
        post_comment(topic, self.author, "Merci, @Titus, qu’en pensez-vous ?")
        self.assertIn(Verb.COMMENT_POSTED, self.verbs(self.other))
        self.assertEqual(self.verbs(self.reader), [Verb.MENTIONED])
        # Its author now follows the discussion.
        post_comment(topic, self.other, "D’accord.")
        self.assertIn(Verb.COMMENT_POSTED, self.verbs(self.author))

    def test_mentions_ignore_spaces_and_case_and_shared_names(self):
        self.assertEqual(mentioned_users("Salut @quintusennius !"), [self.other])
        make_user(email="twin@example.org", display_name="Titus", role=CONTRIBUTOR)
        self.assertEqual(mentioned_users("@Titus"), [])
        self.assertEqual(mentioned_users("écrire à marcus@example.org"), [])

    def test_nobody_is_told_of_what_they_may_not_see(self):
        version = make_version(self.author, self.project)
        follow(self.reader, version)  # refused: a draft of someone else
        self.assertFalse(Subscription.objects.filter(user=self.reader).exists())


class NotificationPageTests(ActivityTestCase):
    def setUp(self):
        self.topic = self.open_topic()
        self.client.force_login(self.author)

    def test_header_shows_the_unread_count(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, 'class="bell-count"')

    def test_opening_a_notification_marks_it_read(self):
        notification = Notification.objects.get(recipient=self.author)
        response = self.client.get(notification.get_absolute_url())
        self.assertRedirects(response, self.topic.get_absolute_url())
        self.assertEqual(unread_count(self.author), 0)

    def test_list_and_mark_all_read(self):
        response = self.client.get(reverse("activity:notifications"))
        self.assertContains(response, "a ouvert un sujet")
        self.client.post(reverse("activity:notifications_read"))
        self.assertEqual(unread_count(self.author), 0)

    def test_notifications_of_others_are_out_of_reach(self):
        notification = Notification.objects.get(recipient=self.author)
        self.client.force_login(self.other)
        response = self.client.get(notification.get_absolute_url())
        self.assertEqual(response.status_code, 404)

    def test_deleting_an_account_deletes_its_notifications(self):
        version = make_published_version(self.reader, self.project)
        star(self.author, version)
        anonymize_user(self.author)
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())
        self.assertFalse(Star.objects.filter(user=self.author).exists())
        self.assertFalse(Subscription.objects.filter(user=self.author).exists())
