"""Years of birth and of death, as they are written.

Years before the common era are held as negative numbers, as in the corpus catalogue.
When an author is only known to have lived in a century, both years hold the first year of
that century, and only the century is shown (choice of 21 September 2026).
"""

from django.utils.translation import gettext, pgettext

NUMERALS = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def format_year(year):
    """« 1885 », or « 44 av. J.-C. » for a negative year; empty when the year is unknown."""
    if year is None:
        return ""
    if year < 0:
        return gettext("%(year)d av. J.-C.") % {"year": -year}
    return str(year)


def roman(number):
    """The number written in Roman numerals: 19 gives XIX."""
    if number < 1:
        return ""
    written = []
    for value, numeral in NUMERALS:
        count, number = divmod(number, value)
        written.append(numeral * count)
    return "".join(written)


def century_of(year):
    """The century a year opens, or None when it opens none.

    Both ways of counting are taken: 1800 and 1801 open the 19th century, 100 and 99 before
    the common era open the 1st century before it. The year zero does not exist.
    """
    if year is None or year == 0:
        return None
    if year > 0:
        return year // 100 + 1 if year % 100 in (0, 1) else None
    years = -year
    if years % 100 == 0:
        return years // 100
    return years // 100 + 1 if years % 100 == 99 else None


def figures_ordinal(number):
    """« 1st », « 2nd », « 19th »: the ordinal of a language that writes it in figures."""
    if number % 100 in (11, 12, 13):
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def century_numeral(century):
    """« XIXe » where centuries are written in Roman numerals, « 19th » where they are not.

    A language that writes them in figures translates the marker below as « figures ».
    """
    if pgettext("century numerals", "roman") == "figures":
        return figures_ordinal(century)
    return f"{roman(century)}{'er' if century == 1 else 'e'}"


def century_label(year):
    """« XIXe siècle », « Ier siècle av. J.-C. »; empty when the year opens no century."""
    century = century_of(year)
    if century is None:
        return ""
    values = {"numeral": century_numeral(century)}
    if year < 0:
        return gettext("%(numeral)s siècle av. J.-C.") % values
    return gettext("%(numeral)s siècle") % values


def author_dates(birth_year, death_year):
    """The dates of an author as they are shown next to their name.

    The same year twice, opening a century, means the author is only situated in that century.
    """
    if birth_year is not None and birth_year == death_year:
        century = century_label(birth_year)
        if century:
            return century
    birth = format_year(birth_year)
    death = format_year(death_year)
    if birth and death:
        return gettext("né en %(birth)s, mort en %(death)s") % {"birth": birth, "death": death}
    if birth:
        return gettext("né en %(birth)s") % {"birth": birth}
    if death:
        return gettext("mort en %(death)s") % {"death": death}
    return ""
