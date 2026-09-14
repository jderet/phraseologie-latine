"""Public-domain translations shown beside the Latin (Q27): their catalogue and their import.

The catalogue lives in corpus/data/translations.csv. A translation is imported only if it is
in the public domain in Europe: its translator died more than 70 years ago, or, when the date
of death is unknown, it was published at least 170 years ago.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .catalog import DATA_DIR, CatalogError
from .models import URN_PREFIX, ReferenceTranslation, TranslationPart, Work
from .perseus import read_translation

COLUMNS = (
    "work",
    "language",
    "file",
    "translator",
    "died",
    "published",
    "milestone",
    "uncited",
    "exclude",
)
SOURCE_NAME = "Perseus canonical-latinLit"
# The translation is in the public domain; its digitization by Perseus is under this licence.
LICENSE = "CC BY-SA 4.0"
# A translator who published can hardly have died more than 100 years later.
YEARS_AFTER_PUBLICATION = 170
YEARS_AFTER_DEATH = 70


class TranslationImportFailed(ValueError):
    pass


@dataclass(frozen=True)
class TranslationEntry:
    work: str
    language: str
    file: str
    translator: str
    died: int | None
    published: int | None
    milestone: str
    uncited: tuple[str, ...]
    exclude: str

    def is_public_domain(self, year):
        if self.died is not None:
            return self.died + YEARS_AFTER_DEATH < year
        return self.published is not None and self.published + YEARS_AFTER_PUBLICATION <= year


def _year(value, errors, where, column):
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(
            _("%(where)s : « %(value)s » n’est pas une année (colonne %(column)s)")
            % {"where": where, "value": value, "column": column}
        )
        return None


def load_translations(directory=DATA_DIR, year=None):
    """Read and check the catalogue of translations; raise CatalogError listing the problems."""
    year = year or timezone.now().year
    path = Path(directory) / "translations.csv"
    errors, entries = [], []
    if not path.is_file():
        raise CatalogError([_("fichier introuvable : %(path)s") % {"path": path}])
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise CatalogError(
                [
                    _("translations.csv : colonnes manquantes : %(columns)s")
                    % {"columns": ", ".join(missing)}
                ]
            )
        for number, row in enumerate(reader, start=2):
            where = _("translations.csv, ligne %(line)d") % {"line": number}
            values = {key: (row.get(key) or "").strip() for key in COLUMNS}
            entry = TranslationEntry(
                work=values["work"],
                language=values["language"],
                file=values["file"],
                translator=values["translator"],
                died=_year(values["died"], errors, where, "died"),
                published=_year(values["published"], errors, where, "published"),
                milestone=values["milestone"],
                uncited=tuple(part for part in values["uncited"].split("|") if part),
                exclude=values["exclude"],
            )
            for column in ("work", "language", "file", "translator"):
                if not values[column]:
                    errors.append(
                        _("%(where)s : la colonne « %(column)s » est vide")
                        % {"where": where, "column": column}
                    )
            file_path = PurePosixPath(entry.file)
            if file_path.is_absolute() or ".." in file_path.parts or file_path.suffix != ".xml":
                errors.append(
                    _("%(where)s : chemin de fichier non valable : %(path)s")
                    % {"where": where, "path": entry.file}
                )
            if entry.exclude:
                try:
                    re.compile(entry.exclude)
                except re.error:
                    errors.append(
                        _("%(where)s : expression d’exclusion non valable") % {"where": where}
                    )
            if not entry.is_public_domain(year):
                errors.append(
                    _(
                        "%(where)s : %(translator)s n’est pas dans le domaine public "
                        "(mort depuis plus de %(years)d ans, ou parution connue depuis %(old)d ans)"
                    )
                    % {
                        "where": where,
                        "translator": entry.translator,
                        "years": YEARS_AFTER_DEATH,
                        "old": YEARS_AFTER_PUBLICATION,
                    }
                )
            entries.append(entry)
    if errors:
        raise CatalogError(errors)
    return entries


@transaction.atomic
def import_translation(entry, source, source_version):
    """Store a translation and its parts; return (translation, created).

    A translation already imported for this version of the source is left untouched; a new
    version replaces the translation in use.
    """
    existing = ReferenceTranslation.objects.filter(
        source_path=entry.file, source_version=source_version
    ).first()
    if existing is not None:
        return existing, False
    work = Work.objects.filter(cts_urn=URN_PREFIX + entry.work).first()
    if work is None:
        raise TranslationImportFailed(_("œuvre inconnue : %(work)s") % {"work": entry.work})
    parsed = read_translation(
        Path(source) / entry.file,
        milestone=entry.milestone,
        uncited=entry.uncited,
        exclude=entry.exclude,
    )
    parts = [passage for passage in parsed.passages if passage.reference and passage.text]
    if not parts:
        raise TranslationImportFailed(_("aucune partie trouvée"))
    references = [part.reference for part in parts]
    doubles = sorted({ref for ref in references if references.count(ref) > 1})
    if doubles:
        raise TranslationImportFailed(
            _("références en double : %(references)s") % {"references": ", ".join(doubles[:20])}
        )
    ReferenceTranslation.objects.filter(work=work, source_path=entry.file, is_current=True).update(
        is_current=False
    )
    translation = ReferenceTranslation.objects.create(
        work=work,
        language=entry.language,
        translator=entry.translator,
        translator_death_year=entry.died,
        published=entry.published,
        source=SOURCE_NAME,
        source_path=entry.file,
        source_version=source_version,
        license=LICENSE,
    )
    TranslationPart.objects.bulk_create(
        [
            TranslationPart(
                translation=translation, order=order, reference=part.reference, text=part.text
            )
            for order, part in enumerate(parts)
        ],
        batch_size=1000,
    )
    return translation, True
