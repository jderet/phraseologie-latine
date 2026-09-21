from django.urls import reverse

from translations import members
from translations.tests.factories import make_version

from .test_notifications import ActivityTestCase


class WorkshopTests(ActivityTestCase):
    def test_login_required(self):
        response = self.client.get(reverse("activity:workshop"))
        self.assertEqual(response.status_code, 302)

    def test_desk_gathers_versions_and_invitations(self):
        draft = make_version(self.author, self.project)
        members.invite(draft, self.author, self.other)
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("activity:workshop")), "vous invite à écrire")
        self.client.force_login(self.author)
        response = self.client.get(reverse("activity:workshop"))
        self.assertContains(response, reverse("translations:version_edit", args=[draft.pk]))

    def test_desk_of_someone_else_is_never_shown(self):
        draft = make_version(self.author, self.project)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("activity:workshop"))
        self.assertNotContains(response, reverse("translations:version_edit", args=[draft.pk]))
