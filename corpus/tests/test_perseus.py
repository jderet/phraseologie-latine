import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from corpus.perseus import PerseusError, git_revision, read_edition

from .utils import FIXTURES

DATA = FIXTURES / "data"


class ProseEditionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.edition = read_edition(DATA / "prose.xml")
        cls.passages = {passage.reference: passage for passage in cls.edition.passages}

    def test_urn_and_citation_scheme(self):
        self.assertEqual(self.edition.urn, "urn:cts:latinLit:phi0474.phi055.perseus-lat1")
        self.assertEqual(self.edition.citation_scheme, ["book", "section"])

    def test_passages_are_the_cited_sections_without_editorial_divisions(self):
        self.assertEqual(list(self.passages), ["1.1", "1.2", "2.1"])

    def test_text_keeps_the_author_and_leaves_out_the_editor(self):
        self.assertEqual(
            self.passages["1.1"].text,
            "Quamquam te, Marce fili, annum iam audientem Cratippum Athenis.",
        )
        self.assertEqual(
            self.passages["1.2"].text, "consilium cepit, ut ait ἀρετή et kai M. Tullius."
        )

    def test_headings_go_to_the_first_passage(self):
        self.assertEqual(self.passages["1.1"].heading, "Liber primus")
        self.assertEqual(self.passages["1.2"].heading, "")

    def test_words_in_greek_or_marked_as_greek_are_foreign(self):
        tokens = self.passages["1.2"].tokens
        self.assertEqual([t.form for t in tokens if t.is_foreign], ["ἀρετή", "kai"])

    def test_paragraphs_and_lines_are_separated_by_a_space(self):
        self.assertEqual(self.passages["2.1"].text, "Quid multa? arma virumque cano")

    def test_tokens_rebuild_the_text(self):
        for passage in self.edition.passages:
            with self.subTest(reference=passage.reference):
                rebuilt = "".join(t.before + t.form + t.after for t in passage.tokens)
                self.assertEqual(rebuilt, passage.text)


class OtherStructuresTests(SimpleTestCase):
    def test_letters_without_sections_are_cited_by_letter(self):
        edition = read_edition(DATA / "letters.xml")
        self.assertEqual(edition.citation_scheme, ["book", "letter", "section"])
        self.assertEqual([p.reference for p in edition.passages], ["1.1.1", "1.1.2", "1.2"])
        self.assertEqual(edition.passages[0].heading, "CICERO ATTICO SAL.")

    def test_divisions_skipped_by_the_citation_are_left_out_of_references(self):
        edition = read_edition(DATA / "wrapped.xml")
        self.assertEqual([p.reference for p in edition.passages], ["1s", "1.pr.1", "1.1.1"])

    def test_excluded_references(self):
        edition = read_edition(DATA / "wrapped.xml", exclude=r"\d+s")
        self.assertEqual([p.reference for p in edition.passages], ["1.pr.1", "1.1.1"])

    def test_verse_lines_and_unnumbered_lines(self):
        edition = read_edition(DATA / "verse.xml")
        self.assertEqual(edition.citation_scheme, ["line"])
        self.assertEqual([p.reference for p in edition.passages], ["1", "2", "3"])
        self.assertEqual(edition.passages[1].text, "Lucina, custos quaeque domituram freta")
        self.assertNotIn("Medea", " ".join(p.text for p in edition.passages))

    def test_verse_keeps_the_speaker_out_of_the_text(self):
        edition = read_edition(DATA / "verse.xml")
        self.assertEqual(edition.passages[0].speaker, "Medea")
        self.assertEqual(edition.passages[1].speaker, "Medea")
        self.assertEqual(edition.passages[2].speaker, "")

    def test_play_keeps_scenes_and_speakers(self):
        edition = read_edition(DATA / "play.xml")
        self.assertEqual(edition.citation_scheme, ["line"])
        self.assertEqual([p.reference for p in edition.passages], ["1", "2", "3", "4", "5"])
        self.assertEqual(edition.passages[0].heading, "Prologue")
        self.assertEqual(edition.passages[0].speaker, "Mercvrivs")
        self.assertEqual(edition.passages[1].heading, "Acte 1 · Scène 1")
        self.assertEqual(edition.passages[1].speaker, "Sosia")
        self.assertEqual(edition.passages[2].heading, "")
        self.assertEqual(edition.passages[2].speaker, "Sosia")
        self.assertEqual(edition.passages[3].speaker, "Mercvrivs")
        self.assertEqual(edition.passages[4].heading, "Acte 1 · Scène 2")
        self.assertEqual(edition.passages[4].speaker, "Ivppiter")

    def test_verse_cited_by_division_and_line(self):
        edition = read_edition(DATA / "verse_books.xml")
        self.assertEqual(edition.citation_scheme, ["poem", "line"])
        self.assertEqual([p.reference for p in edition.passages], ["1.1", "1.2", "2.1", "2.2"])
        self.assertEqual(edition.passages[1].text, "numquamne reponam vexatus totiens")
        self.assertNotIn("Satura", " ".join(p.text for p in edition.passages))

    def test_undeclared_html_entities_are_read(self):
        edition = read_edition(DATA / "verse_books.xml")
        self.assertEqual(edition.passages[2].text, "Ultra Sauromatas † fugere hinc libet")

    def test_sections_in_numbered_segments(self):
        edition = read_edition(DATA / "sections.xml")
        self.assertEqual(edition.citation_scheme, ["chapter", "section"])
        self.assertEqual([p.reference for p in edition.passages], ["1.1", "1.2", "2.1"])
        self.assertEqual(edition.passages[0].heading, "M. Porcius Cato")
        self.assertEqual(edition.passages[1].text, "primum stipendium meruit in Sicilia.")

    def test_older_file_with_numbered_divisions_and_milestones(self):
        edition = read_edition(DATA / "phi1351.phi005.perseus-lat1.xml")
        self.assertEqual(edition.urn, "urn:cts:latinLit:phi1351.phi005.perseus-lat1")
        self.assertEqual(edition.citation_scheme, ["book", "chapter"])
        self.assertEqual([p.reference for p in edition.passages], ["1.1", "1.2", "2"])
        first, second = edition.passages[:2]
        self.assertEqual(first.heading, "Annales · LIBER I")
        self.assertTrue(first.text.startswith("Urbem Romam"))
        self.assertTrue(first.text.endswith("dictaturae ad tempus sumebantur;"))
        self.assertEqual(second.text, "sed † veteris populi Romani δόξα memorata sunt.")
        self.assertEqual([t.form for t in second.tokens if t.is_foreign], ["δόξα"])
        for passage in edition.passages:
            rebuilt = "".join(t.before + t.form + t.after for t in passage.tokens)
            self.assertEqual(rebuilt, passage.text)

    def test_invalid_xml(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "broken.xml"
            path.write_text("<TEI><text>&iacute;</TEI>")
            with self.assertRaises(PerseusError):
                read_edition(path)

    def test_file_without_edition(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "empty.xml"
            path.write_text("<TEI><text><body><p>Nihil</p></body></text></TEI>")
            with self.assertRaises(PerseusError):
                read_edition(path)


class GitRevisionTests(SimpleTestCase):
    def test_branch_reference_and_packed_references(self):
        with tempfile.TemporaryDirectory() as name:
            git = Path(name) / ".git"
            (git / "refs" / "heads").mkdir(parents=True)
            (git / "HEAD").write_text("ref: refs/heads/master\n")
            (git / "packed-refs").write_text("# pack-refs\n" + "b" * 40 + " refs/heads/master\n")
            self.assertEqual(git_revision(name), "b" * 40)
            (git / "refs" / "heads" / "master").write_text("c" * 40 + "\n")
            self.assertEqual(git_revision(name), "c" * 40)

    def test_detached_head(self):
        with tempfile.TemporaryDirectory() as name:
            (Path(name) / ".git").mkdir()
            (Path(name) / ".git" / "HEAD").write_text("d" * 40 + "\n")
            self.assertEqual(git_revision(name), "d" * 40)
