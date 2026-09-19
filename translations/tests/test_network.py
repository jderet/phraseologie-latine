from django.urls import reverse

from translations.models import TranslationVersion
from translations.network import copy_network
from translations.services import copy_version, publish_version, save_translation
from translations.steps import public_step

from .factories import make_published_version
from .test_versions import TranslationTestCase


class NetworkTests(TranslationTestCase):
    def copy(self, version, user):
        return copy_version(public_step(version), TranslationVersion(), user)

    def test_variants_with_their_drift(self):
        original = make_published_version(self.author, self.project)
        first_copy = self.copy(original, self.other)
        save_translation(first_copy, self.first, "Imber cadit.", self.other)
        publish_version(first_copy, self.other)
        first_copy.refresh_from_db()
        second_copy = self.copy(original, self.reviewer)
        ancestors, nodes = copy_network(self.reviewer, original)
        self.assertEqual(ancestors, [])
        self.assertEqual(
            [(node.version, node.depth) for node in nodes], [(first_copy, 1), (second_copy, 1)]
        )
        self.assertEqual(nodes[0].differing, 1)
        # A draft variant is seen by its writers only.
        _ancestors, public_nodes = copy_network(self.author, original)
        self.assertEqual([node.version for node in public_nodes], [first_copy])
        ancestors, _nodes = copy_network(self.reviewer, second_copy)
        self.assertEqual(ancestors, [original])

    def test_page(self):
        original = make_published_version(self.author, self.project)
        response = self.client.get(reverse("translations:version_network", args=[original.pk]))
        self.assertContains(response, "Personne n’a encore proposé de variante.")
