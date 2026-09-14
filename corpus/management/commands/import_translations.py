from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils.translation import gettext as _

from corpus.catalog import DATA_DIR, CatalogError
from corpus.perseus import PerseusError, git_revision
from corpus.translations import TranslationImportFailed, import_translation, load_translations


class Command(BaseCommand):
    help = "Import the public-domain translations listed in corpus/data/translations.csv."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=Path,
            default=settings.PERSEUS_LATIN_DIR,
            help="clone of canonical-latinLit",
        )
        parser.add_argument(
            "--catalog", type=Path, default=DATA_DIR, help="directory of translations.csv"
        )

    def handle(self, *args, **options):
        try:
            entries = load_translations(options["catalog"])
        except CatalogError as error:
            raise CommandError(str(error)) from error
        source = options["source"]
        try:
            version = git_revision(source)
        except (OSError, PerseusError) as error:
            raise CommandError(
                _("Version du dépôt Perseus illisible dans %(path)s.") % {"path": source}
            ) from error
        for entry in entries:
            try:
                translation, created = import_translation(entry, source, version)
            except (TranslationImportFailed, PerseusError, OSError, DatabaseError) as error:
                raise CommandError(f"{entry.file} : {error}") from error
            counts = {
                "work": entry.work,
                "translator": entry.translator,
                "parts": translation.parts.count(),
            }
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        _("%(work)s, %(translator)s : %(parts)d parties importées") % counts
                    )
                )
            else:
                self.stdout.write(_("%(work)s, %(translator)s : déjà importée") % counts)
