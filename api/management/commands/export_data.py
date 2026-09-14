from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from api.export import write_export


class Command(BaseCommand):
    help = "Write the full export of the public data as a zip archive of JSON files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir", type=Path, default=settings.EXPORT_DIR, help="directory of the archive"
        )

    def handle(self, *args, **options):
        path, counts = write_export(options["output_dir"])
        for name, count in counts.items():
            self.stdout.write(f"{name} : {count}")
        self.stdout.write(self.style.SUCCESS(_("Export écrit : %(path)s") % {"path": path}))
