from django.test import SimpleTestCase
from django.utils import translation

from .dates import (
    author_dates,
    century_label,
    century_of,
    figures_ordinal,
    format_year,
    roman,
)


class RomanNumeralTests(SimpleTestCase):
    def test_numbers_are_written_as_numerals(self):
        cases = [(1, "I"), (4, "IV"), (9, "IX"), (14, "XIV"), (19, "XIX"), (20, "XX"), (21, "XXI")]
        for number, numeral in cases:
            with self.subTest(number=number):
                self.assertEqual(roman(number), numeral)


class CenturyTests(SimpleTestCase):
    def test_a_first_year_of_a_century_gives_that_century(self):
        for year, century in [(1, 1), (1800, 19), (1801, 19), (1900, 20), (1901, 20)]:
            with self.subTest(year=year):
                self.assertEqual(century_of(year), century)

    def test_the_same_holds_before_the_common_era(self):
        for year, century in [(-100, 1), (-99, 1), (-200, 2), (-199, 2)]:
            with self.subTest(year=year):
                self.assertEqual(century_of(year), century)

    def test_any_other_year_opens_no_century(self):
        for year in (0, None, 1802, 1850, -55, -101):
            with self.subTest(year=year):
                self.assertIsNone(century_of(year))

    def test_the_century_is_written_with_its_numeral(self):
        self.assertEqual(century_label(1800), "XIXe siècle")
        self.assertEqual(century_label(1), "Ier siècle")
        self.assertEqual(century_label(-100), "Ier siècle av. J.-C.")
        self.assertEqual(century_label(-199), "IIe siècle av. J.-C.")
        self.assertEqual(century_label(1802), "")


class FormatYearTests(SimpleTestCase):
    def test_years_before_the_common_era_are_said_so(self):
        self.assertEqual(format_year(1885), "1885")
        self.assertEqual(format_year(-44), "44 av. J.-C.")
        self.assertEqual(format_year(None), "")


class AuthorDatesTests(SimpleTestCase):
    def test_two_equal_years_opening_a_century_show_the_century_alone(self):
        self.assertEqual(author_dates(1800, 1800), "XIXe siècle")
        self.assertEqual(author_dates(-100, -100), "Ier siècle av. J.-C.")

    def test_two_equal_years_opening_no_century_are_shown_as_they_are(self):
        self.assertEqual(author_dates(1802, 1802), "né en 1802, mort en 1802")

    def test_both_years_are_shown_when_they_are_known(self):
        self.assertEqual(author_dates(1802, 1885), "né en 1802, mort en 1885")

    def test_one_year_alone(self):
        self.assertEqual(author_dates(1802, None), "né en 1802")
        self.assertEqual(author_dates(None, 1885), "mort en 1885")

    def test_no_year_at_all(self):
        self.assertEqual(author_dates(None, None), "")

    def test_english_writes_its_ordinals_in_figures(self):
        for number, written in [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (21, "21st")]:
            with self.subTest(number=number):
                self.assertEqual(figures_ordinal(number), written)
        with translation.override("en"):
            self.assertEqual(author_dates(1800, 1800), "19th century")
            self.assertEqual(author_dates(-100, -100), "1st century BC")
            self.assertEqual(author_dates(1802, 1885), "born 1802, died 1885")
