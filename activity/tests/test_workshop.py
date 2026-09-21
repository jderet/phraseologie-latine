from django.urls import reverse

from translations import members
from translations.models import SegmentVariant
from translations.tests.factories import make_published_version, make_version
from translations.variants import add_variant

from .test_notifications import ActivityTestCase


class WorkshopTests(ActivityTestCase):
    def test_login_required(self):
        response = self.client.get(reverse("activity:workshop"))
        self.assertEqual(response.status_code, 302)

    def test_desk_gathers_versions_and_invitations(self):
        draft = make_version(self.author, self.project)
        members.invite(self.project, self.author, self.other)
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse("activity:workshop")), "vous invite à être")
        self.client.force_login(self.author)
        response = self.client.get(reverse("activity:workshop"))
        self.assertContains(response, reverse("translations:version_edit", args=[draft.pk]))

    def test_desk_shows_the_variants_to_decide(self):
        version = make_published_version(self.author, self.project)
        add_variant(
            SegmentVariant(
                version=version, segment=self.first, text="Imber cadit.", comment="Mieux."
            ),
            self.reader,
        )
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse("activity:workshop")), "Imber cadit.")
        self.client.force_login(self.reader)
        page = self.client.get(reverse("activity:workshop"))
        self.assertContains(page, "Vos variantes en attente")

    def test_desk_of_someone_else_is_never_shown(self):
        draft = make_version(self.author, self.project)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("activity:workshop"))
        self.assertNotContains(response, reverse("translations:version_edit", args=[draft.pk]))
