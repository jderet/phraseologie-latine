from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from corpus.models import Edition
from corpus.reading import Page, ReadingPlan, plan_pages, reading_rows

from .test_translations import MILLER, catalog
from .utils import PerseusSourceMixin

BOOKS = ["book", "section"]
CHAPTERS = ["book", "chapter", "section"]


def rows(*passages):
    """(order, reference, characters) of passages given as (reference, characters)."""
    return [(order, reference, size) for order, (reference, size) in enumerate(passages, start=1)]


def passages(*references):
    return [
        SimpleNamespace(pk=order, reference=reference, heading="", text="")
        for order, reference in enumerate(references, start=1)
    ]


class PlanTests(SimpleTestCase):
    def keys(self, pages):
        return [page.key for page in pages]

    def test_a_short_work_is_read_on_one_page(self):
        (page,) = plan_pages(rows(("1.1", 10), ("1.2", 10), ("2.1", 10)), 2, size=100)
        self.assertTrue(page.whole)
        self.assertEqual((page.start, page.end, page.key, page.label(BOOKS)), (1, 3, "", ""))

    def test_each_book_that_fits_makes_a_page(self):
        pages = plan_pages(rows(("1.1", 10), ("1.2", 10), ("2.1", 10)), 2, size=25)
        self.assertEqual(self.keys(pages), ["1", "2"])
        self.assertEqual([(page.start, page.end) for page in pages], [(1, 2), (3, 3)])
        self.assertEqual([page.label(BOOKS) for page in pages], ["Livre 1", "Livre 2"])

    def test_short_divisions_are_read_together(self):
        letters = rows(*((f"{number}.1", 10) for number in range(1, 5)))
        pages = plan_pages(letters, 2, size=25)
        self.assertEqual(self.keys(pages), ["1-2", "3-4"])
        self.assertEqual(pages[0].label(["letter", "section"]), "Lettres 1 à 2")

    def test_a_book_too_long_is_split_into_chapters(self):
        livy = rows(("1.1.1", 10), ("1.1.2", 10), ("1.2.1", 10), ("1.3.1", 10), ("2.1.1", 5))
        pages = plan_pages(livy, 3, size=25)
        self.assertEqual(self.keys(pages), ["1.1", "1.2-1.3", "2"])
        self.assertEqual(
            [page.label(CHAPTERS) for page in pages],
            ["Livre 1, chapitre 1", "Livre 1, chapitres 2 à 3", "Livre 2"],
        )

    def test_the_lines_of_a_poem(self):
        lines = rows(*((str(number), 10) for number in range(1, 11)))
        pages = plan_pages(lines, 1, size=30)
        self.assertEqual(self.keys(pages), ["1-3", "4-6", "7-9", "10"])
        self.assertEqual(pages[0].label(["line"]), "Vers 1 à 3")

    def test_a_passage_longer_than_a_page_stands_alone(self):
        pages = plan_pages(rows(("1", 50), ("2", 10)), 1, size=30)
        self.assertEqual(self.keys(pages), ["1", "2"])

    def test_finding_a_page(self):
        pages = plan_pages(rows(("1.1", 10), ("1.2", 10), ("2.1", 10)), 2, size=25)
        plan = ReadingPlan(BOOKS, pages)
        self.assertEqual([plan.page_at(order).key for order in (1, 2, 3)], ["1", "1", "2"])
        self.assertEqual(plan.page("2"), pages[1])
        self.assertIsNone(plan.page("3"))


class RowTests(SimpleTestCase):
    def headings(self, page, references):
        found = reading_rows(page, CHAPTERS, passages(*references), {}, {})
        return [item.headings for row in found for item in row.items]

    def test_headings_name_the_divisions_the_title_does_not(self):
        references = ("1.1.1", "1.1.2", "1.2.1")
        self.assertEqual(
            self.headings(Page(1, 3, whole=True), references),
            [["Livre 1", "Chapitre 1"], [], ["Chapitre 2"]],
        )
        book = Page(1, 3, first="1", last="1")
        self.assertEqual(self.headings(book, references), [["Chapitre 1"], [], ["Chapitre 2"]])
        chapters = Page(1, 3, parent=("1",), first="1", last="2")
        self.assertEqual(self.headings(chapters, references), [["Chapitre 1"], [], ["Chapitre 2"]])

    def test_rows_follow_the_parts_of_the_translation(self):
        first, second = object(), object()
        parts = {"1.1": first, "1.2": first, "2.1": second}
        found = reading_rows(
            Page(1, 3, whole=True), BOOKS, passages("1.1", "1.2", "2.1"), {}, parts
        )
        self.assertEqual(
            [[item.passage.reference for item in row.items] for row in found],
            [["1.1", "1.2"], ["2.1"]],
        )
        self.assertIs(found[0].part, first)

    def test_verse_is_numbered_every_five_lines(self):
        lines = passages(*(str(number) for number in range(1, 7)))
        (row,) = reading_rows(Page(1, 6, whole=True), ["line"], lines, {}, {}, verse=True)
        self.assertEqual([item.quiet for item in row.items], [True, True, True, True, False, True])


class ReadingPageTests(PerseusSourceMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.import_corpus()

    def url(self, part=None, work="phi0474.phi055"):
        if part is None:
            return reverse("corpus:reading", args=[work])
        return reverse("corpus:reading_part", args=[work, part])

    def import_translation(self):
        call_command(
            "import_translations",
            "--source",
            str(self.source),
            "--catalog",
            str(catalog(MILLER)),
            stdout=StringIO(),
        )

    def test_a_short_work_on_one_page_with_its_books(self):
        response = self.client.get(self.url())
        self.assertContains(response, "<h1><i>De officiis</i></h1>", html=True)
        self.assertContains(response, '<h2 class="reading-heading">Livre 2</h2>', html=True)
        self.assertContains(response, ">Quamquam</span> <span")
        self.assertContains(response, 'id="p-2.1"')
        passage = reverse("corpus:passage", args=["phi0474.phi055", "1.2"])
        self.assertContains(response, f'href="{passage}"')
        self.assertContains(response, f'href="{self.url()}#p-2.1"')
        self.assertNotContains(response, 'rel="next"')
        self.assertNotContains(response, 'class="page-wide"')

    def test_the_translation_beside_the_latin_can_be_hidden(self):
        self.import_translation()
        response = self.client.get(self.url())
        self.assertContains(response, 'class="page-wide"')
        self.assertContains(response, "He took counsel, as he says, of virtue.")
        self.assertContains(response, f'href="{self.url()}?traduction=non"')
        hidden = self.client.get(self.url(), {"traduction": "non"})
        self.assertNotContains(hidden, "He took counsel")
        self.assertNotContains(hidden, 'class="page-wide"')
        self.assertContains(hidden, "Afficher la traduction")
        self.assertContains(hidden, 'name="traduction" value="non"')

    def test_going_to_a_passage(self):
        response = self.client.get(self.url(), {"aller": "1, 2"})
        self.assertRedirects(response, f"{self.url()}#p-1.2", fetch_redirect_response=False)
        self.import_translation()
        response = self.client.get(self.url(), {"aller": "2", "traduction": "non"})
        expected = f"{self.url()}?traduction=non#p-2.1"
        self.assertRedirects(response, expected, fetch_redirect_response=False)
        response = self.client.get(self.url(), {"aller": "9"})
        self.assertContains(response, "Aucun passage « 9 » dans cette édition.")

    def test_a_long_work_is_read_page_by_page(self):
        edition = Edition.objects.get(work__cts_urn__endswith="phi0474.phi055", is_current=True)
        sizes = {passage.reference: len(passage.text) for passage in edition.passages.all()}
        with mock.patch("corpus.reading.PAGE_SIZE", sizes["1.1"] + sizes["1.2"]):
            first = self.client.get(self.url())
            second = self.client.get(self.url("2"))
            missing = self.client.get(self.url("3"))
            jump = self.client.get(self.url(), {"aller": "2.1"})
        self.assertContains(first, "<h1>Livre 1</h1>", html=True)
        self.assertContains(first, f'<a rel="next" href="{self.url("2")}">Livre 2 →</a>', html=True)
        self.assertNotContains(first, ">multa</span>")
        self.assertContains(second, ">multa</span>")
        self.assertContains(second, f'rel="prev" href="{self.url("1")}"')
        self.assertContains(second, f'href="{self.url("1")}#p-1.1"')
        self.assertEqual(missing.status_code, 404)
        self.assertRedirects(jump, f"{self.url('2')}#p-2.1", fetch_redirect_response=False)

    def test_the_work_and_passage_pages_lead_to_the_reading(self):
        work = self.client.get(reverse("corpus:work", args=["phi0474.phi055"]))
        self.assertContains(work, f'href="{self.url()}"')
        passage = self.client.get(reverse("corpus:passage", args=["phi0474.phi055", "1.2"]))
        self.assertContains(passage, f'href="{self.url()}?aller=1.2"')

    def test_letters_and_verse(self):
        letters = self.client.get(self.url(work="phi0474.phi057"))
        self.assertContains(letters, '<h2 class="reading-heading">Lettre 2</h2>', html=True)
        self.assertContains(letters, "CICERO ATTICO SAL.")
        verse = self.client.get(self.url(work="phi1017.phi004"))
        self.assertContains(verse, "reading-verse")
        self.assertContains(verse, "Poésie : ne fait pas norme pour la prose.")
