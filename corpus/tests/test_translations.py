import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from corpus.catalog import CatalogError
from corpus.models import ReferenceTranslation
from corpus.perseus import read_translation
from corpus.translations import load_translations

from .utils import FIXTURES, PerseusSourceMixin

HEADER = "work,language,file,translator,died,published,milestone,uncited,exclude\n"
MILLER = "phi0474.phi055,en,data/prose-eng.xml,Walter Miller,1949,1913,section,chapter,\n"


def catalog(*rows):
    directory = Path(tempfile.mkdtemp())
    shutil.copy(FIXTURES / "catalog" / "authors.csv", directory / "authors.csv")
    shutil.copy(FIXTURES / "catalog" / "works.csv", directory / "works.csv")
    (directory / "translations.csv").write_text(HEADER + "".join(rows))
    return directory


class TranslationReaderTests(SimpleTestCase):
    def test_a_translation_cut_at_its_section_milestones(self):
        parsed = read_translation(
            FIXTURES / "data" / "prose-eng.xml", milestone="section", uncited=("chapter",)
        )
        self.assertEqual([p.reference for p in parsed.passages], ["1.1", "1.2", "2.1"])
        self.assertEqual(parsed.passages[1].text, "He took counsel, as he says, of virtue.")

    def test_a_text_right_in_the_body_and_books_numbered_twice(self):
        parsed = read_translation(FIXTURES / "data" / "speech-eng.xml", milestone="section")
        self.assertEqual([p.reference for p in parsed.passages], ["1", "2"])
        self.assertEqual(parsed.passages[1].text, "then I shall be grateful.")
        parsed = read_translation(FIXTURES / "data" / "books-eng.xml", milestone="section")
        self.assertEqual([p.reference for p in parsed.passages], ["1.1", "2.1", "3.1"])

    def test_a_translation_cut_by_its_citation_patterns(self):
        parsed = read_translation(FIXTURES / "data" / "prose-eng.xml")
        self.assertEqual([p.reference for p in parsed.passages], ["1", "2"])


class TranslationCatalogTests(SimpleTestCase):
    def test_only_public_domain_translations_are_accepted(self):
        (entry,) = load_translations(catalog(MILLER), year=2026)
        self.assertEqual((entry.died, entry.uncited), (1949, ("chapter",)))
        recent = "phi0474.phi055,en,data/prose-eng.xml,Someone,1960,1951,,,\n"
        unknown_old = "phi0474.phi055,en,data/prose-eng.xml,McDevitte,,1851,,,\n"
        unknown_recent = "phi0474.phi055,en,data/prose-eng.xml,Anonymous,,1900,,,\n"
        self.assertEqual(len(load_translations(catalog(unknown_old), year=2026)), 1)
        for row in (recent, unknown_recent):
            with self.subTest(row=row), self.assertRaises(CatalogError) as caught:
                load_translations(catalog(row), year=2026)
            self.assertIn("domaine public", str(caught.exception))


class TranslationImportTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()
        self.catalog = catalog(MILLER)

    def run_import(self):
        call_command(
            "import_translations",
            "--source",
            str(self.source),
            "--catalog",
            str(self.catalog),
            stdout=StringIO(),
        )

    def test_import_and_display_beside_the_latin(self):
        self.run_import()
        translation = ReferenceTranslation.objects.get()
        self.assertEqual(translation.parts.count(), 3)
        self.assertEqual(
            translation.part_for("1.2").text, "He took counsel, as he says, of virtue."
        )
        self.run_import()
        self.assertEqual(ReferenceTranslation.objects.count(), 1)
        page = self.client.get(reverse("corpus:passage", args=["phi0474.phi055", "1.2"]))
        self.assertContains(page, "Traduction de Walter Miller")
        self.assertContains(page, "He took counsel")
        self.assertContains(page, "Traduction du domaine public")
        self.assertNotContains(page, "découpée que plus largement")

    def test_a_coarser_part_is_shown_for_a_finer_reference(self):
        self.catalog = catalog(MILLER.replace("section,chapter", ","))
        self.run_import()
        page = self.client.get(reverse("corpus:passage", args=["phi0474.phi055", "1.2"]))
        self.assertContains(page, "voici tout le passage 1")
        self.assertContains(page, "My dear son Marcus")

    def test_an_unknown_work_stops_the_import(self):
        self.catalog = catalog(MILLER.replace("phi0474.phi055", "phi0474.phi999"))
        with self.assertRaises(CommandError):
            self.run_import()
