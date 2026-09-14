import time

from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext as _

from corpus.search import default_layer
from phraseology.candidates import MIN_FREQUENCY, MIN_SCORE, extract_candidates


class Command(BaseCommand):
    help = "Extract candidate units from the analysed corpus into the review queue (on the Mac)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-frequency",
            type=int,
            default=MIN_FREQUENCY,
            help=f"minimum number of occurrences of a pair (default {MIN_FREQUENCY})",
        )
        parser.add_argument(
            "--min-score",
            type=float,
            default=MIN_SCORE,
            help=f"minimum log-likelihood score (default {MIN_SCORE})",
        )
        parser.add_argument(
            "--all-corpus",
            action="store_true",
            help="count pairs in the whole corpus instead of the core only",
        )

    def handle(self, *args, **options):
        layer = default_layer()
        if layer is None:
            raise CommandError(_("Aucune couche d’analyse par défaut : lancer analyze_corpus."))
        started = time.monotonic()
        result = extract_candidates(
            layer,
            core_only=not options["all_corpus"],
            min_frequency=options["min_frequency"],
            min_score=options["min_score"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                _(
                    "Candidats : %(created)d nouveaux, %(updated)d mis à jour, "
                    "%(removed)d retirés, en %(seconds)d s."
                )
                % {**result, "seconds": time.monotonic() - started}
            )
        )
