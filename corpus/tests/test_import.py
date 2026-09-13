from django.core.management import CommandError
from django.test import TestCase

from corpus.models import Author, Edition, Passage, Token, Work

from .utils import PerseusSourceMixin

OFFICES = "urn:cts:latinLit:phi0474.phi055"


class ImportPerseusTests(PerseusSourceMixin, TestCase):
    def test_import_creates_authors_works_passages_and_words(self):
        output = self.import_corpus()
        self.assertIn("phi0474.phi055", output)
        self.assertEqual(Author.objects.count(), 3)
        self.assertEqual(Work.objects.count(), 4)
        self.assertEqual(Edition.objects.filter(is_current=True).count(), 4)
        edition = Edition.objects.get(work__cts_urn=OFFICES)
        self.assertEqual(edition.source_version, "a" * 40)
        self.assertEqual(edition.passage_count, 3)
        positions = list(edition.tokens.values_list("position", flat=True))
        self.assertEqual(positions, list(range(edition.token_count)))
        word = edition.tokens.get(form="Athenis")
        self.assertEqual((word.norm, word.passage.reference, word.after), ("athenis", "1.1", "."))
        self.assertTrue(edition.tokens.get(form="kai").is_foreign)

    def test_catalog_metadata_is_stored(self):
        self.import_corpus()
        medea = Work.objects.get(cts_urn="urn:cts:latinLit:phi1017.phi004")
        self.assertFalse(medea.is_core)
        self.assertEqual(medea.form, Work.Form.VERSE)
        self.assertEqual(medea.citation_prefix, "Sen. Med.")

    def test_excluded_passages_are_not_imported(self):
        self.import_corpus()
        livy = Edition.objects.get(work__cts_urn="urn:cts:latinLit:phi0914.phi001")
        self.assertEqual(
            list(livy.passages.values_list("reference", flat=True)), ["1.pr.1", "1.1.1"]
        )

    def test_importing_the_same_version_again_changes_nothing(self):
        self.import_corpus()
        tokens = Token.objects.count()
        output = self.import_corpus()
        self.assertIn("déjà importée", output)
        self.assertEqual((Edition.objects.count(), Token.objects.count()), (4, tokens))

    def test_a_new_version_becomes_current_and_the_old_edition_stays(self):
        self.import_corpus("--work", "phi0474.phi055")
        old = Edition.objects.get()
        old_words = list(old.tokens.values_list("pk", flat=True))
        self.set_version("b" * 40)
        self.import_corpus("--work", "phi0474.phi055")
        old.refresh_from_db()
        self.assertFalse(old.is_current)
        self.assertEqual(Edition.objects.get(is_current=True).source_version, "b" * 40)
        self.assertEqual(list(old.tokens.values_list("pk", flat=True)), old_words)

    def test_dry_run_writes_nothing(self):
        output = self.import_corpus("--dry-run")
        self.assertIn("passages", output)
        self.assertFalse(Work.objects.exists())

    def test_metadata_only_updates_the_catalogue_without_texts(self):
        self.import_corpus("--metadata-only")
        self.assertEqual(Work.objects.count(), 4)
        self.assertFalse(Passage.objects.exists())

    def test_unknown_work_is_refused(self):
        with self.assertRaises(CommandError):
            self.import_corpus("--work", "phi9999.phi001")

    def test_duplicate_references_stop_the_import(self):
        path = self.source / "data" / "letters.xml"
        path.write_text(
            path.read_text().replace('subtype="section" n="2"', 'subtype="section" n="1"')
        )
        with self.assertRaises(CommandError) as raised:
            self.import_corpus("--work", "phi0474.phi057")
        self.assertIn("1.1.1", str(raised.exception))
        self.assertFalse(Edition.objects.exists())
