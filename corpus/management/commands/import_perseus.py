from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError
from django.utils.translation import gettext as _

from corpus.catalog import DATA_DIR, CatalogError, load_catalog
from corpus.importer import ImportFailed, import_edition, sync_author, sync_work
from corpus.perseus import PerseusError, git_revision, read_edition


class Command(BaseCommand):
    help = "Import the Perseus editions listed in corpus/data/works.csv (run on the Mac)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--work",
            action="append",
            default=[],
            metavar="ID",
            help="work to import, e.g. phi0474.phi055 (repeatable; all works by default)",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="read the files without writing anything"
        )
        parser.add_argument(
            "--metadata-only",
            action="store_true",
            help="update authors and works from the catalogue without reading the texts",
        )
        parser.add_argument(
            "--source",
            type=Path,
            default=settings.PERSEUS_LATIN_DIR,
            help="clone of canonical-latinLit",
        )
        parser.add_argument(
            "--catalog", type=Path, default=DATA_DIR, help="directory of authors.csv and works.csv"
        )

    def handle(self, *args, **options):
        try:
            catalog = load_catalog(options["catalog"])
        except CatalogError as error:
            raise CommandError(str(error)) from error
        entries = self._selected(catalog, options["work"])
        if options["metadata_only"]:
            for entry in entries:
                sync_work(entry, sync_author(catalog.authors[entry.author]))
            self.stdout.write(
                _("Catalogue mis à jour : %(count)d œuvres.") % {"count": len(entries)}
            )
            return
        source = options["source"]
        try:
            version = git_revision(source)
        except (OSError, PerseusError) as error:
            raise CommandError(
                _("Version du dépôt Perseus illisible dans %(path)s.") % {"path": source}
            ) from error
        for entry in entries:
            self._import(catalog, entry, source, version, options["dry_run"])

    def _selected(self, catalog, wanted):
        if not wanted:
            return catalog.works
        entries = [e for e in catalog.works if e.cts_id in wanted or e.cts_urn in wanted]
        unknown = set(wanted) - {e.cts_id for e in entries} - {e.cts_urn for e in entries}
        if unknown:
            raise CommandError(
                _("Œuvres absentes du catalogue : %(works)s")
                % {"works": ", ".join(sorted(unknown))}
            )
        return entries

    def _import(self, catalog, entry, source, version, dry_run):
        try:
            parsed = read_edition(source / entry.edition_file, entry.exclude)
        except (OSError, PerseusError) as error:
            raise CommandError(f"{entry.cts_id} : {error}") from error
        counts = {
            "work": entry.cts_id,
            "passages": len(parsed.passages),
            "tokens": parsed.token_count,
        }
        if dry_run:
            self.stdout.write(_("%(work)s : %(passages)d passages, %(tokens)d mots") % counts)
            return
        try:
            work = sync_work(entry, sync_author(catalog.authors[entry.author]))
            _edition, created = import_edition(work, parsed, entry.edition_file, version)
        except (ImportFailed, DatabaseError) as error:
            raise CommandError(f"{entry.cts_id} : {error}") from error
        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    _("%(work)s : %(passages)d passages, %(tokens)d mots importés") % counts
                )
            )
        else:
            self.stdout.write(_("%(work)s : déjà importée pour cette version de Perseus") % counts)
