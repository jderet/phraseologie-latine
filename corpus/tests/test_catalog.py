import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from corpus.catalog import DATA_DIR, CatalogError, load_catalog

from .utils import CATALOG

CORE_AUTHORS = {"phi0474", "phi0448", "phi0631", "phi0914", "phi1017", "phi1318"}


class ProjectCatalogTests(SimpleTestCase):
    def test_catalog_of_the_project_is_valid(self):
        catalog = load_catalog(DATA_DIR)
        self.assertEqual(len(catalog.works), 90)
        self.assertEqual({work.author for work in catalog.works if work.is_core}, CORE_AUTHORS)

    def test_seneca_tragedies_are_outside_the_core(self):
        tragedies = [w for w in load_catalog(DATA_DIR).works if w.genre == "tragedy"]
        self.assertEqual(len(tragedies), 10)
        self.assertFalse(any(work.is_core for work in tragedies))

    @skipUnless(settings.PERSEUS_LATIN_DIR.is_dir(), "Perseus clone not available")
    def test_every_edition_file_exists(self):
        for work in load_catalog(DATA_DIR).works:
            with self.subTest(work=work.cts_id):
                self.assertTrue((settings.PERSEUS_LATIN_DIR / work.edition_file).is_file())


class CatalogValidationTests(SimpleTestCase):
    def load_with_works(self, rows):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            shutil.copy(CATALOG / "authors.csv", directory / "authors.csv")
            header = (CATALOG / "works.csv").read_text().splitlines()[0]
            (directory / "works.csv").write_text("\n".join([header, *rows]) + "\n")
            return load_catalog(directory)

    def test_fixture_catalog_is_valid(self):
        self.assertEqual(len(load_catalog(CATALOG).works), 4)

    def test_errors_name_the_line_and_the_problem(self):
        rows = [
            "urn:cts:latinLit:phi0474.phi055,phi0474,data/prose.xml,De officiis,Off.,"
            "poetry,elevated,prose,-44,-44,oui,non,",
            "urn:cts:latinLit:phi0474.phi056,phi9999,../secret.xml,Fam.,Fam.,"
            "letters,familiar,prose,x,-43,peut-être,non,(",
        ]
        with self.assertRaises(CatalogError) as raised:
            self.load_with_works(rows)
        message = str(raised.exception)
        for expected in (
            "ligne 2",
            "poetry",
            "ligne 3",
            "phi9999",
            "../secret.xml",
            "« x »",
            "peut-être",
            "expression",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, message)
