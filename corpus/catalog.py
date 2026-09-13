"""Catalogue of the corpus: authors and works to import, with their metadata.

It lives in two CSV files (corpus/data/authors.csv and works.csv), so that it can be read
and corrected in a spreadsheet. See corpus/data/README.md.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from django.utils.translation import gettext as _

from .models import URN_PREFIX, Period, Work

DATA_DIR = Path(__file__).resolve().parent / "data"
AUTHOR_COLUMNS = (
    "cts_id",
    "name_fr",
    "name_en",
    "latin_name",
    "abbreviation",
    "birth_year",
    "death_year",
    "period",
)
WORK_COLUMNS = (
    "cts_urn",
    "author",
    "edition_file",
    "title",
    "abbreviation",
    "genre",
    "register",
    "form",
    "date_from",
    "date_to",
    "is_core",
    "is_fragmentary",
    "exclude",
)
BOOLEANS = {"oui": True, "non": False, "true": True, "false": False, "1": True, "0": False}
URN_PATTERN = re.compile(re.escape(URN_PREFIX) + r"[a-z]+\d+\.[a-z]+\d+")


class CatalogError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


@dataclass(frozen=True)
class AuthorEntry:
    cts_id: str
    name_fr: str
    name_en: str
    latin_name: str
    abbreviation: str
    birth_year: int | None
    death_year: int | None
    period: str


@dataclass(frozen=True)
class WorkEntry:
    cts_urn: str
    author: str
    edition_file: str
    title: str
    abbreviation: str
    genre: str
    register: str
    form: str
    date_from: int | None
    date_to: int | None
    is_core: bool
    is_fragmentary: bool
    exclude: str

    @property
    def cts_id(self):
        return self.cts_urn.removeprefix(URN_PREFIX)


@dataclass(frozen=True)
class Catalog:
    authors: dict[str, AuthorEntry]
    works: list[WorkEntry]


class _Row:
    def __init__(self, filename, number, values, errors):
        self.filename = filename
        self.number = number
        self.values = values
        self.errors = errors

    def error(self, message):
        self.errors.append(
            _("%(file)s, ligne %(line)d : %(message)s")
            % {"file": self.filename, "line": self.number, "message": message}
        )

    def text(self, column, required=False):
        value = (self.values.get(column) or "").strip()
        if required and not value:
            self.error(_("la colonne « %(column)s » est vide") % {"column": column})
        return value

    def year(self, column):
        value = self.text(column)
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            self.error(
                _("« %(value)s » n’est pas une année (colonne %(column)s)")
                % {"value": value, "column": column}
            )
            return None

    def boolean(self, column):
        value = self.text(column).lower()
        if value not in BOOLEANS:
            self.error(
                _("« %(value)s » : écrire oui ou non (colonne %(column)s)")
                % {"value": value, "column": column}
            )
            return False
        return BOOLEANS[value]

    def choice(self, column, allowed, required=False):
        value = self.text(column, required)
        if value and value not in allowed:
            self.error(
                _("« %(value)s » n’est pas permis dans la colonne %(column)s (%(allowed)s)")
                % {"value": value, "column": column, "allowed": ", ".join(allowed)}
            )
        return value


def _rows(path, columns, errors):
    if not path.is_file():
        errors.append(_("fichier introuvable : %(path)s") % {"path": path})
        return []
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        missing = [column for column in columns if column not in (reader.fieldnames or [])]
        if missing:
            errors.append(
                _("%(file)s : colonnes manquantes : %(columns)s")
                % {"file": path.name, "columns": ", ".join(missing)}
            )
            return []
        return [(number, values) for number, values in enumerate(reader, start=2)]


def _load_authors(directory, errors):
    authors = {}
    for number, values in _rows(directory / "authors.csv", AUTHOR_COLUMNS, errors):
        row = _Row("authors.csv", number, values, errors)
        entry = AuthorEntry(
            cts_id=row.text("cts_id", required=True),
            name_fr=row.text("name_fr", required=True),
            name_en=row.text("name_en", required=True),
            latin_name=row.text("latin_name", required=True),
            abbreviation=row.text("abbreviation", required=True),
            birth_year=row.year("birth_year"),
            death_year=row.year("death_year"),
            period=row.choice("period", Period.values),
        )
        if entry.cts_id in authors:
            row.error(_("auteur en double : %(author)s") % {"author": entry.cts_id})
        authors[entry.cts_id] = entry
    return authors


def _check_work(row, entry, authors, seen):
    if entry.cts_urn and not URN_PATTERN.fullmatch(entry.cts_urn):
        row.error(_("URN CTS mal formée : %(urn)s") % {"urn": entry.cts_urn})
    if entry.cts_urn in seen:
        row.error(_("œuvre en double : %(urn)s") % {"urn": entry.cts_urn})
    if entry.author and entry.author not in authors:
        row.error(_("auteur inconnu : %(author)s") % {"author": entry.author})
    path = PurePosixPath(entry.edition_file)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".xml":
        row.error(_("chemin de fichier non valable : %(path)s") % {"path": entry.edition_file})
    if entry.date_from is not None and entry.date_to is not None:
        if entry.date_from > entry.date_to:
            row.error(_("la date de début est postérieure à la date de fin"))
    if entry.exclude:
        try:
            re.compile(entry.exclude)
        except re.error:
            row.error(
                _("expression d’exclusion non valable : %(pattern)s") % {"pattern": entry.exclude}
            )


def load_catalog(directory=DATA_DIR):
    """Read and check the catalogue; raise CatalogError listing every problem found."""
    directory = Path(directory)
    errors = []
    authors = _load_authors(directory, errors)
    works = []
    seen = set()
    for number, values in _rows(directory / "works.csv", WORK_COLUMNS, errors):
        row = _Row("works.csv", number, values, errors)
        entry = WorkEntry(
            cts_urn=row.text("cts_urn", required=True),
            author=row.text("author", required=True),
            edition_file=row.text("edition_file", required=True),
            title=row.text("title", required=True),
            abbreviation=row.text("abbreviation"),
            genre=row.choice("genre", Work.Genre.values),
            register=row.choice("register", Work.Register.values),
            form=row.choice("form", Work.Form.values, required=True),
            date_from=row.year("date_from"),
            date_to=row.year("date_to"),
            is_core=row.boolean("is_core"),
            is_fragmentary=row.boolean("is_fragmentary"),
            exclude=row.text("exclude"),
        )
        _check_work(row, entry, authors, seen)
        seen.add(entry.cts_urn)
        works.append(entry)
    if errors:
        raise CatalogError(errors)
    return Catalog(authors, works)
