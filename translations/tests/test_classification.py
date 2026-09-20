"""Genres and themes of the texts to translate (choice of 20 September 2026)."""

from django.test import TestCase
from django.urls import reverse

from accounts.roles import CONTRIBUTOR, REVIEWER
from accounts.tests.factories import make_user
from moderation.services import hide_content
from translations.classification import (
    GENRE_GROUPS,
    MAX_GENRES,
    MAX_THEMES,
    THEME_GROUPS,
    Genre,
    Theme,
    clean_codes,
    grouped_choices,
    names,
)
from translations.forms import SourceTextEditForm

from .factories import make_source_text


class VocabularyTests(TestCase):
    def test_every_value_belongs_to_one_family(self):
        for groups, choices in ((GENRE_GROUPS, Genre), (THEME_GROUPS, Theme)):
            listed = [value for _, values in groups for value in values]
            with self.subTest(choices=choices.__name__):
                self.assertEqual(sorted(listed), sorted(choices.values))

    def test_unknown_and_repeated_codes_are_dropped(self):
        codes = [Genre.FABLE, "licorne", Genre.NOVEL, Genre.FABLE]
        # The order of the list, not that of the answer.
        self.assertEqual(clean_codes(codes, Genre), [Genre.NOVEL, Genre.FABLE])
        self.assertEqual(clean_codes(None, Theme), [])

    def test_names_pair_each_code_with_its_label(self):
        self.assertEqual(names([Theme.WAR], Theme), [(Theme.WAR, Theme.WAR.label)])

    def test_the_menus_are_grouped_by_family(self):
        families = grouped_choices(GENRE_GROUPS)
        self.assertEqual(len(families), len(GENRE_GROUPS))
        family, options = families[0]
        self.assertEqual(str(family), "Récits")
        self.assertIn((Genre.NOVEL, Genre.NOVEL.label), options)


class SourceTextRulesTests(TestCase):
    def setUp(self):
        self.user = make_user(role=CONTRIBUTOR)
        self.source = make_source_text(self.user)

    def form(self, **fields):
        data = {
            "title": self.source.title,
            "author": "",
            "language": "fr",
            "license": self.source.license,
            "source_url": self.source.source_url,
            "genres": [Genre.FABLE],
            "themes": [],
            "level_names": "",
        } | fields
        return SourceTextEditForm(data, instance=self.source, user=self.user)

    def test_a_text_without_a_genre_is_refused(self):
        form = self.form(genres=[])
        self.assertFalse(form.is_valid())
        self.assertIn("genres", form.errors)

    def test_an_unknown_genre_is_refused(self):
        form = self.form(genres=["licorne"])
        self.assertFalse(form.is_valid())
        self.assertIn("genres", form.errors)

    def test_the_number_of_genres_and_themes_is_limited(self):
        form = self.form(genres=Genre.values[: MAX_GENRES + 1])
        self.assertFalse(form.is_valid())
        self.assertIn("genres", form.errors)
        form = self.form(themes=Theme.values[: MAX_THEMES + 1])
        self.assertFalse(form.is_valid())
        self.assertIn("themes", form.errors)

    def test_the_codes_are_saved_in_the_order_of_the_list(self):
        form = self.form(genres=[Genre.FABLE, Genre.NOVEL], themes=[Theme.ANIMALS, Theme.WAR])
        self.assertTrue(form.is_valid(), form.errors)
        source = form.save()
        self.assertEqual(source.genres, [Genre.NOVEL, Genre.FABLE])
        self.assertEqual(source.themes, [Theme.WAR, Theme.ANIMALS])
        self.assertEqual(source.genre_names[0], (Genre.NOVEL, Genre.NOVEL.label))


class ClassifiedPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user(email="owner@example.org", role=CONTRIBUTOR, is_confirmed=True)
        cls.fable = make_source_text(
            cls.user, title="Le corbeau", genres=[Genre.FABLE], themes=[Theme.ANIMALS]
        )
        cls.speech = make_source_text(
            cls.user, title="Le discours", genres=[Genre.SPEECH], themes=[Theme.POLITICS]
        )

    def test_the_list_is_filtered_by_genre_and_by_theme(self):
        url = reverse("translations:source_list")
        response = self.client.get(url, {"genre": Genre.FABLE})
        self.assertContains(response, "Le corbeau")
        self.assertNotContains(response, "Le discours")
        response = self.client.get(url, {"theme": Theme.POLITICS, "tri": "etoiles"})
        self.assertContains(response, "Le discours")
        self.assertNotContains(response, "Le corbeau")

    def test_an_unknown_filter_is_ignored(self):
        response = self.client.get(reverse("translations:source_list"), {"genre": "licorne"})
        self.assertContains(response, "Le corbeau")
        self.assertContains(response, "Le discours")

    def test_each_genre_and_each_theme_has_its_own_page(self):
        response = self.client.get(reverse("translations:source_by_genre", args=[Genre.FABLE]))
        self.assertContains(response, "Le corbeau")
        self.assertNotContains(response, "Le discours")
        self.assertContains(response, "Genre : fable")
        response = self.client.get(reverse("translations:source_by_theme", args=[Theme.ANIMALS]))
        self.assertContains(response, "Le corbeau")
        self.assertNotContains(response, "Le discours")

    def test_an_unknown_code_is_not_a_page(self):
        for name in ("source_by_genre", "source_by_theme"):
            with self.subTest(page=name):
                url = reverse(f"translations:{name}", args=["licorne"])
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_a_hidden_text_is_not_in_its_genre(self):
        hide_content(self.fable, make_user(email="reviewer@example.org", role=REVIEWER))
        url = reverse("translations:source_by_genre", args=[Genre.FABLE])
        self.assertNotContains(self.client.get(url), "Le corbeau")

    def test_the_page_of_a_text_shows_its_genres_and_its_themes(self):
        response = self.client.get(self.fable.get_absolute_url())
        self.assertContains(response, reverse("translations:source_by_genre", args=[Genre.FABLE]))
        self.assertContains(response, reverse("translations:source_by_theme", args=[Theme.ANIMALS]))
