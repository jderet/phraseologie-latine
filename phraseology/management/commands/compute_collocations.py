import time

from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _

from corpus.search import default_layer
from phraseology.collocations import MIN_FREQUENCY, compute_collocations
from phraseology.models import Collocation


class Command(BaseCommand):
    help = "Count the collocations of the analysed corpus for the lemma profiles (on the Mac)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-frequency",
            type=int,
            default=MIN_FREQUENCY,
            help=f"minimum number of occurrences of a pair (default {MIN_FREQUENCY})",
        )

    def handle(self, *args, **options):
        layer = default_layer()
        if layer is None:
            raise CommandError(_("Aucune couche d’analyse par défaut : lancer analyze_corpus."))
        started = time.monotonic()
        counts = compute_collocations(layer, min_frequency=options["min_frequency"])
        for scope, count in counts.items():
            self.stdout.write(
                _("%(scope)s : %(count)d paires")
                % {"scope": Collocation.Scope(scope).label, "count": count}
            )
        self.stdout.write(
            self.style.SUCCESS(
                _("Collocations calculées en %(seconds)d s.")
                % {"seconds": time.monotonic() - started}
            )
        )
