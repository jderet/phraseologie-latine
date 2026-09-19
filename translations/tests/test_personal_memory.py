from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.services import anonymize_user
from translations.models import PersonalMemoryEntry

from .factories import make_version
from .test_versions import TranslationTestCase

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4"><header srclang="fr"/><body>
<tu><tuv xml:lang="fr"><seg>Nous restons à la maison ce soir.</seg></tuv>
<tuv xml:lang="la"><seg>Hodie vesperi domi manemus.</seg></tuv></tu>
<tu><tuv xml:lang="fr"><seg>Sans latin.</seg></tuv>
<tuv xml:lang="en"><seg>No Latin.</seg></tuv></tu>
</body></tmx>"""


class PersonalMemoryTests(TranslationTestCase):
    def setUp(self):
        self.client.force_login(self.author)
        self.url = reverse("translations:personal_memory")

    def upload(self, content=TMX):
        return self.client.post(
            self.url, {"file": SimpleUploadedFile("anciennes.tmx", content.encode())}
        )

    def test_import_keeps_pairs_with_latin_once(self):
        self.upload()
        self.upload()
        entry = PersonalMemoryEntry.objects.get()
        self.assertEqual(
            (entry.user, entry.language, entry.origin), (self.author, "fr", "anciennes.tmx")
        )

    def test_offered_in_the_editor_to_its_owner_only(self):
        self.upload()
        version = make_version(self.author, self.project)
        url = reverse("translations:editor_memory", args=[version.pk, self.second.pk])
        self.assertContains(self.client.get(url), "Hodie vesperi domi manemus.")
        other_version = make_version(self.other, self.project)
        self.client.force_login(self.other)
        url = reverse("translations:editor_memory", args=[other_version.pk, self.second.pk])
        self.assertNotContains(self.client.get(url), "Hodie vesperi")

    def test_erase_and_account_deletion(self):
        self.upload()
        self.client.post(self.url, {"action": "effacer"})
        self.assertFalse(PersonalMemoryEntry.objects.exists())
        self.upload()
        anonymize_user(self.author)
        self.assertFalse(PersonalMemoryEntry.objects.exists())

    def test_refuses_other_files(self):
        response = self.upload("<xliff/>")
        self.assertContains(response, "n’est pas un fichier TMX")
