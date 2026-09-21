import datetime as dt

from django.urls import reverse
from django.utils import timezone

from activity.feeds import activity_calendar, contributor_feed, project_feed
from activity.models import Event, Verb
from translations import members
from translations.services import create_step, publish_version
from translations.tests.factories import make_published_version, make_version, translate

from .test_notifications import ActivityTestCase


class FeedTests(ActivityTestCase):
    def test_project_feed_shows_public_events_only(self):
        version = make_version(self.author, self.project)
        translate(version)
        create_step(version, self.author, "Brouillon")
        publish_version(version, self.author)
        verbs = [event.verb for event in project_feed(self.reader, self.project)]
        self.assertEqual(verbs, [Verb.VERSION_PUBLISHED])

    def test_invitations_never_appear_in_feeds(self):
        make_published_version(self.author, self.project)
        members.invite(self.project, self.author, self.other)
        verbs = [event.verb for event in contributor_feed(self.reader, self.author)]
        self.assertNotIn(Verb.MEMBER_INVITED, verbs)

    def test_project_activity_tab(self):
        make_published_version(self.author, self.project)
        response = self.client.get(reverse("translations:project_activity", args=[self.project.pk]))
        self.assertContains(response, "a publié une version")

    def test_calendar_counts_public_events_by_day(self):
        make_published_version(self.author, self.project)
        calendar = activity_calendar(self.author)
        self.assertEqual(calendar["total"], 1)
        self.assertEqual(len(calendar["weeks"]), 52)
        today = [
            day
            for week in calendar["weeks"]
            for day in week
            if day["date"] == timezone.localdate(Event.objects.get().created_at)
        ]
        self.assertEqual(today[0]["level"], 1)

    def test_calendar_leaves_the_future_empty(self):
        calendar = activity_calendar(self.author, today=dt.date(2026, 9, 16))
        last_week = calendar["weeks"][-1]
        self.assertIsNone(last_week[6]["count"])


class ProfileTests(ActivityTestCase):
    def test_profile_lists_published_versions_and_actions(self):
        version = make_published_version(self.author, self.project)
        response = self.client.get(reverse("accounts:profile", args=[self.author.pk]))
        self.assertContains(response, version.get_absolute_url())
        self.assertContains(response, "a publié une version")
        self.assertContains(response, "activity-calendar")

    def test_profile_hides_drafts(self):
        version = make_version(self.author, self.project)
        response = self.client.get(reverse("accounts:profile", args=[self.author.pk]))
        self.assertNotContains(response, version.get_absolute_url())

    def test_own_profile_tells_how_to_be_mentioned(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("accounts:profile", args=[self.other.pk]))
        self.assertContains(response, "@QuintusEnnius")
