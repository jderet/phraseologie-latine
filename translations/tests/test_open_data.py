import xml.etree.ElementTree as ET

from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from activity.models import Star
from translations import glossary, members, topics
from translations.models import GlossaryEntry, Topic

from .factories import make_published_version
from .test_versions import TranslationTestCase


class OpenDataTests(TranslationTestCase):
    def setUp(self):
        self.version = make_published_version(self.author, self.project)
        member = members.invite(self.version, self.author, self.other)
        members.answer(member, self.other, accept=True)
        Star.objects.create(user=self.reviewer, version=self.version)
        self.version.steps.filter(number=1).update(label="Édition 1")
        glossary.propose_term(
            GlossaryEntry(project=self.project, source_term="maison", latin_term="domus"),
            self.author,
        )
        # Proposed by someone who is not a maintainer: it waits for a decision.
        passer_by = make_user(email="passer-by@example.org", role=CONTRIBUTOR, is_confirmed=True)
        glossary.propose_term(
            GlossaryEntry(project=self.project, source_term="pluie", latin_term="imber"),
            passer_by,
        )
        topics.open_topic(Topic(project=self.project, title="Temps", body="?"), self.other)

    def test_version_carries_co_authors_stars_and_editions(self):
        data = self.client.get(reverse("api:version", args=[self.version.pk])).json()
        self.assertEqual(data["co_authors"], ["Quintus"])
        self.assertEqual(data["stars"], 1)
        self.assertEqual([edition["label"] for edition in data["editions"]], ["Édition 1"])

    def test_topics_and_adopted_terms_only(self):
        topics_data = self.client.get(reverse("api:topics")).json()
        self.assertEqual(topics_data["results"][0]["title"], "Temps")
        terms = self.client.get(reverse("api:glossaries")).json()["results"]
        self.assertEqual([term["latin_term"] for term in terms], ["domus"])

    def test_glossary_exports(self):
        csv = self.client.get(
            reverse("translations:glossary_export", args=[self.project.pk, "csv"])
        )
        self.assertEqual(csv.content.decode().splitlines(), ["fr,la,note", "maison,domus,"])
        tbx = self.client.get(
            reverse("translations:glossary_export", args=[self.project.pk, "tbx"])
        )
        root = ET.fromstring(tbx.content)
        self.assertEqual([term.text for term in root.iter("term")], ["maison", "domus"])
        self.assertEqual(
            self.client.get(
                reverse("translations:glossary_export", args=[self.project.pk, "exe"])
            ).status_code,
            404,
        )
