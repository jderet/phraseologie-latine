"""Parts and chapters of a source text: the outline, the citations, the reading page."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.roles import CONTRIBUTOR
from accounts.tests.factories import make_user
from translations.classification import Genre
from translations.models import SourceText
from translations.segmentation import MAX_SENTENCES, segment
from translations.sources import outline, preview_divisions, reading_blocks, under

from .factories import make_project, make_source_text, make_version

BOOK = (
    "# Première partie\n"
    "## Chapitre premier\n"
    "Il pleut. Il vente.\n"
    "## Chapitre second\n"
    "Le ciel est clair.\n"
    "# Seconde partie\n"
    "## Chapitre premier\n"
    "Nous partons."
)


class OutlineTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)
        self.source = make_source_text(self.user, sentences=segment(BOOK, "fr"))
        self.segments = list(self.source.segments.current())
        self.divisions, self.places = outline(self.segments)

    def test_divisions_are_numbered_inside_the_division_that_holds_them(self):
        self.assertEqual(
            [(d.key, d.level, d.index, d.title) for d in self.divisions],
            [
                ("1", 1, 1, "Première partie"),
                ("1.1", 2, 1, "Chapitre premier"),
                ("1.2", 2, 2, "Chapitre second"),
                ("2", 1, 2, "Seconde partie"),
                ("2.1", 2, 1, "Chapitre premier"),
            ],
        )

    def test_the_numbers_of_the_sentences_start_again_in_each_division(self):
        numbers = {
            segment.text: self.places[segment.pk].number
            for segment in self.segments
            if not segment.level
        }
        self.assertEqual(
            numbers,
            {"Il pleut.": 1, "Il vente.": 2, "Le ciel est clair.": 1, "Nous partons.": 1},
        )

    def test_a_sentence_is_cited_by_its_division(self):
        sentence = next(s for s in self.segments if s.text == "Il vente.")
        self.assertEqual(self.source.citation(self.places[sentence.pk]), "Chapitre 1, phrase 2")
        self.source.level_names = "Livre, Section"
        self.assertEqual(self.source.citation(self.places[sentence.pk]), "Section 1, phrase 2")

    def test_a_text_without_division_keeps_its_numbers(self):
        source = make_source_text(self.user, title="Sans division")
        segments = list(source.segments.current())
        _, places = outline(segments)
        self.assertEqual(source.citation(places[segments[2].pk]), "phrase 3")

    def test_one_division_holds_the_divisions_inside_it(self):
        kept = [s.text for s in under(self.segments, self.places, "1")]
        self.assertEqual(
            kept,
            [
                "Première partie",
                "Chapitre premier",
                "Il pleut.",
                "Il vente.",
                "Chapitre second",
                "Le ciel est clair.",
            ],
        )
        self.assertEqual(len(under(self.segments, self.places, "")), len(self.segments))

    def test_sentences_are_grouped_under_their_title(self):
        blocks = reading_blocks(self.segments, self.places)
        self.assertEqual(
            [(block["division"].title, len(block["sentences"])) for block in blocks],
            [
                ("Première partie", 0),
                ("Chapitre premier", 2),
                ("Chapitre second", 1),
                ("Seconde partie", 0),
                ("Chapitre premier", 1),
            ],
        )

    def test_the_usual_names_of_the_levels(self):
        self.assertEqual(self.source.level_label(1), "Partie")
        self.assertEqual(self.source.level_label(3), "Section")
        self.source.level_names = "Livre"
        self.assertEqual(self.source.level_label(1), "Livre")
        self.assertEqual(self.source.level_label(2), "Chapitre")


class PreviewTests(TestCase):
    """The outline shown before a text is saved, so that the hierarchy is checked first."""

    def test_each_division_counts_the_sentences_under_it(self):
        rows, before = preview_divisions(segment(BOOK, "fr"))
        self.assertEqual(before, 0)
        self.assertEqual(
            [(row["division"].key, row["division"].title, row["count"]) for row in rows],
            [
                ("1", "Première partie", 3),
                ("1.1", "Chapitre premier", 2),
                ("1.2", "Chapitre second", 1),
                ("2", "Seconde partie", 1),
                ("2.1", "Chapitre premier", 1),
            ],
        )

    def test_the_sentences_before_the_first_title_are_counted_apart(self):
        rows, before = preview_divisions(segment("Il pleut. Il vente.\n# Partie\nFin.", "fr"))
        self.assertEqual(before, 2)
        self.assertEqual([row["count"] for row in rows], [1])

    def test_a_text_without_title_has_no_outline(self):
        self.assertEqual(preview_divisions(segment("Il pleut. Il vente.", "fr")), ([], 2))


class PreviewPageTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)
        self.client.force_login(self.user)

    def form_data(self, **fields):
        return {
            "title": "Un livre",
            "language": "fr",
            "license": "public-domain",
            "author_death_year": "1200",
            "genres": [Genre.NOVEL],
            "level_names": "Livre, Chapitre",
            "text": BOOK,
            "declaration": "on",
        } | fields

    def test_the_outline_is_shown_before_saving_with_the_chosen_names(self):
        response = self.client.post(reverse("translations:source_create"), self.form_data())
        self.assertContains(response, "Plan du livre")
        self.assertContains(response, "Livre 1")
        self.assertContains(response, "Chapitre 2")
        self.assertContains(response, "Chapitre second")
        self.assertFalse(SourceText.objects.exists())

    def test_the_chosen_names_are_saved_with_the_text(self):
        data = self.form_data()
        response = self.client.post(reverse("translations:source_create"), data)
        checked = response.context["form"]["text"].value()
        self.client.post(
            reverse("translations:source_create"), self.form_data(text=checked, segmented="1")
        )
        source = SourceText.objects.get()
        self.assertEqual(source.level_names, "Livre, Chapitre")
        self.assertEqual(source.level_label(1), "Livre")


class ReadingPageTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)
        self.source = make_source_text(self.user, sentences=segment(BOOK, "fr"))

    def test_the_page_shows_the_outline_and_the_titles(self):
        response = self.client.get(self.source.get_absolute_url())
        self.assertContains(response, "Chapitre second")
        self.assertContains(response, "Tout le texte (4 phrases)")
        self.assertContains(response, "Nous partons.")

    def test_one_division_at_a_time(self):
        response = self.client.get(f"{self.source.get_absolute_url()}?division=2")
        self.assertContains(response, "Nous partons.")
        self.assertNotContains(response, "Il pleut.")

    def test_an_unknown_division_shows_the_whole_text(self):
        response = self.client.get(f"{self.source.get_absolute_url()}?division=9")
        self.assertContains(response, "Il pleut.")
        self.assertContains(response, "Nous partons.")


class EditorTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)
        self.source = make_source_text(self.user, sentences=segment(BOOK, "fr"))
        self.project = make_project(self.user, source_text=self.source)
        self.version = make_version(self.user, self.project)
        self.client.force_login(self.user)

    def url(self):
        return reverse("translations:version_edit", args=[self.version.pk])

    def test_titles_are_rows_the_progress_does_not_count(self):
        response = self.client.get(self.url())
        self.assertEqual(response.context["segment_count"], 4)
        self.assertContains(response, "bitext-heading")
        self.assertContains(response, "Chapitre second")

    def test_the_editor_shows_one_division(self):
        response = self.client.get(f"{self.url()}?division=2")
        texts = [row["segment"].text for row in response.context["shown_rows"]]
        self.assertEqual(texts, ["Seconde partie", "Chapitre premier", "Nous partons."])

    def test_a_title_is_translated_like_a_sentence(self):
        title = self.source.segments.get(level=1, text="Première partie")
        response = self.client.post(self.url(), {f"s{title.pk}": "Pars prima"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.version.segments.get(segment=title).text, "Pars prima")
        self.assertEqual(self.client.get(self.url()).context["translated_count"], 0)


class LongTextTests(TestCase):
    """A whole book is saved in one form: Django's own limit of 1000 fields is too low."""

    def test_more_fields_than_the_django_default_are_accepted(self):
        user = make_user(role=CONTRIBUTOR)
        sentences = [f"Phrase {number}." for number in range(1, 1201)]
        source = make_source_text(user, sentences=sentences)
        project = make_project(user, source_text=source)
        version = make_version(user, project)
        self.client.force_login(user)
        segments = list(source.segments.current())
        data = {f"s{segment.pk}": "" for segment in segments}
        data[f"s{segments[0].pk}"] = "Pluit."
        response = self.client.post(reverse("translations:version_edit", args=[version.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(version.segments.get(segment=segments[0]).text, "Pluit.")

    def test_the_limit_covers_a_text_of_the_greatest_size(self):
        self.assertGreater(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS, MAX_SENTENCES + 100)
