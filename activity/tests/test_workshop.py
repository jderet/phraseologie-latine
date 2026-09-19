from django.urls import reverse

from translations import members
from translations.models import ChangeProposal
from translations.services import create_proposal
from translations.tests.factories import make_published_version, make_version

from .test_notifications import ActivityTestCase


class WorkshopTests(ActivityTestCase):
    def test_login_required(self):
        response = self.client.get(reverse("activity:workshop"))
        self.assertEqual(response.status_code, 302)

    def test_desk_gathers_versions_invitations_and_proposals(self):
        draft = make_version(self.author, self.project)
        published = make_published_version(self.other, self.project)
        members.invite(published, self.other, self.author)
        proposal = create_proposal(
            ChangeProposal(version=published, explanation="Mieux."),
            self.author,
            {self.first: "Pluit multum."},
        )
        other_version = make_published_version(self.author, self.project)
        waiting = create_proposal(
            ChangeProposal(version=other_version, explanation="Autrement."),
            self.reader,
            {self.first: "Imber cadit."},
        )
        self.client.force_login(self.author)
        response = self.client.get(reverse("activity:workshop"))
        self.assertContains(response, reverse("translations:version_edit", args=[draft.pk]))
        self.assertContains(response, "vous invite à co-écrire")
        self.assertContains(response, proposal.get_absolute_url())
        self.assertContains(response, waiting.get_absolute_url())

    def test_desk_of_someone_else_is_never_shown(self):
        draft = make_version(self.author, self.project)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("activity:workshop"))
        self.assertNotContains(response, reverse("translations:version_edit", args=[draft.pk]))
