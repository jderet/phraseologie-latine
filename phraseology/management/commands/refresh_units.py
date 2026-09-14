from django.core.management.base import BaseCommand
from django.utils.translation import ngettext

from phraseology.models import Unit
from phraseology.services import refresh_frequency
from phraseology.spotting import refresh_unit_forms


class Command(BaseCommand):
    help = "Compute again the frequency and the forms of every unit, after a new analysis layer."

    def handle(self, *args, **options):
        count = 0
        for unit in Unit.objects.order_by("pk").iterator():
            refresh_frequency(unit)
            refresh_unit_forms(unit)
            count += 1
        self.stdout.write(
            self.style.SUCCESS(
                ngettext("%(count)d unité mise à jour.", "%(count)d unités mises à jour.", count)
                % {"count": count}
            )
        )
