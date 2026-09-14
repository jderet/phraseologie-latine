import json
import tempfile
import zipfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from api.export import latest_export, write_export

from .test_api import ApiTestCase


class ExportTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_the_command_writes_the_archive_of_public_data(self):
        call_command("export_data", "--output-dir", str(self.directory), stdout=StringIO())
        export = latest_export(self.directory)
        with zipfile.ZipFile(export.path) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "LISEZMOI.txt",
                    "fiches.json",
                    "neologismes.json",
                    "versions.json",
                    "recherches-infructueuses.json",
                },
            )
            units = json.loads(archive.read("fiches.json"))
            self.assertEqual([unit["reference_form"] for unit in units], ["consilium capere"])
            self.assertEqual(units[0]["url"], self.unit.get_absolute_url())
            self.assertIn("CC BY-SA 4.0", archive.read("LISEZMOI.txt").decode())
            everything = "".join(archive.read(name).decode() for name in archive.namelist())
        self.assertNotIn("Pluit secretum", everything)
        self.assertNotIn("consilia capere", everything)
        self.assertNotIn("@example.org", everything)

    def test_the_data_page_and_the_download(self):
        with override_settings(EXPORT_DIR=self.directory):
            page = self.client.get(reverse("api:data"))
            self.assertContains(page, "Aucun export n’a encore été produit.")
            self.assertEqual(self.client.get(reverse("api:export")).status_code, 404)
            path, _counts = write_export()
            page = self.client.get(reverse("api:data"))
            self.assertContains(page, "Télécharger l’archive")
            self.assertContains(page, path.name)
            response = self.client.get(reverse("api:export"))
            self.assertEqual(response.status_code, 200)
            self.assertIn(f'filename="{path.name}"', response["Content-Disposition"])
            content = b"".join(response.streaming_content)
        self.assertTrue(content.startswith(b"PK"))

    def test_the_footer_links_to_open_data(self):
        self.assertContains(self.client.get("/"), reverse("api:data"))
