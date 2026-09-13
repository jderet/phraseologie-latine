import argparse
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from corpus.analysis import analyze_edition
from corpus.models import URN_PREFIX, AnalysisLayer, Edition


class Command(BaseCommand):
    help = "Analyse the current editions with LatinCy into a new analysis layer (run on the Mac)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--work",
            action="append",
            default=[],
            metavar="ID",
            help="work to analyse, e.g. phi0474.phi055 (repeatable; all works by default)",
        )
        parser.add_argument("--model", default="la_core_web_lg", help="spaCy model")
        parser.add_argument(
            "--layer", type=int, help="complete an existing layer instead of creating a new one"
        )
        parser.add_argument(
            "--make-default", action="store_true", help="use the layer for lemma search"
        )
        parser.add_argument(
            "--analyzer", default="corpus.analysis.SpacyAnalyzer", help=argparse.SUPPRESS
        )

    def handle(self, *args, **options):
        editions = self._editions(options["work"])
        try:
            analyzer = import_string(options["analyzer"])(options["model"])
        except (ImportError, OSError) as error:
            raise CommandError(
                _("Analyseur indisponible (%(error)s) : installer requirements-corpus.txt.")
                % {"error": error}
            ) from error
        layer = self._layer(options["layer"], analyzer)
        done = set(layer.editions.values_list("pk", flat=True))
        for edition in editions:
            work = edition.work.cts_id
            if edition.pk in done:
                self.stdout.write(_("%(work)s : déjà analysée dans cette couche") % {"work": work})
                continue
            started = time.monotonic()
            rows = analyze_edition(edition, layer, analyzer)
            self.stdout.write(
                _("%(work)s : %(rows)d analyses en %(seconds)d s")
                % {"work": work, "rows": rows, "seconds": time.monotonic() - started}
            )
        if options["make_default"]:
            layer.make_default()
        self.stdout.write(
            self.style.SUCCESS(
                _("Couche %(layer)d : %(editions)d éditions analysées.")
                % {"layer": layer.pk, "editions": layer.editions.count()}
            )
        )

    def _editions(self, works):
        editions = (
            Edition.objects.filter(is_current=True)
            .select_related("work")
            .order_by("work__author__birth_year", "work__cts_urn")
        )
        if works:
            urns = {URN_PREFIX + work for work in works}
            editions = editions.filter(work__cts_urn__in=urns)
            missing = urns - set(editions.values_list("work__cts_urn", flat=True))
            if missing:
                raise CommandError(
                    _("Œuvres non importées : %(works)s")
                    % {"works": ", ".join(sorted(urn.removeprefix(URN_PREFIX) for urn in missing))}
                )
        return editions

    def _layer(self, layer_id, analyzer):
        if layer_id is None:
            return AnalysisLayer.objects.create(
                tool=analyzer.tool, tool_version=analyzer.tool_version, details=analyzer.details
            )
        try:
            return AnalysisLayer.objects.get(pk=layer_id)
        except AnalysisLayer.DoesNotExist as error:
            raise CommandError(
                _("Couche d’analyse inconnue : %(layer)d") % {"layer": layer_id}
            ) from error
