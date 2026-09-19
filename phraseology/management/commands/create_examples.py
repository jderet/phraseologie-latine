from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.translation import gettext, ngettext

from corpus.models import Work
from corpus.search import default_layer
from phraseology.examples import (
    EXAMPLES,
    FOCUS_WORK,
    attestation_counts,
    check_development,
    create_example,
    create_example_abstracts,
    example_accounts,
    example_units,
)


class Command(BaseCommand):
    help = "Create example units on a development machine, to see phraseology in the texts."

    def handle(self, *args, **options):
        check_development()
        layer = default_layer()
        if layer is None:
            raise CommandError(gettext("Les fiches d’exemple demandent un corpus analysé."))
        focus = Work.objects.filter(cts_urn=FOCUS_WORK, editions__is_current=True).first()
        if focus is None:
            raise CommandError(
                gettext("Les fiches d’exemple partent du De officiis, qui n’est pas importé.")
            )
        if example_units().exists():
            raise CommandError(
                gettext("Les fiches d’exemple existent déjà : lancez d’abord delete_examples.")
            )
        created = 0
        with transaction.atomic():
            author, reviewer = example_accounts()
            create_example_abstracts(author, reviewer)
            for example in EXAMPLES:
                unit = create_example(example, focus, layer, author, reviewer)
                if unit is None:
                    self.stdout.write(
                        self.style.WARNING(
                            gettext("%(unit)s : introuvable dans le corpus, fiche non créée.")
                            % {"unit": example.reference_form}
                        )
                    )
                    continue
                created += 1
                self.stdout.write(
                    gettext(
                        "%(unit)s (%(status)s) : attestations validées %(validated)d, "
                        "proposées %(proposed)d, repérées automatiquement %(automatic)d."
                    )
                    % {
                        "unit": unit.reference_form,
                        "status": unit.get_status_display(),
                        **attestation_counts(unit),
                    }
                )
        self.stdout.write(
            self.style.SUCCESS(
                ngettext(
                    "%(count)d fiche d’exemple créée.",
                    "%(count)d fiches d’exemple créées.",
                    created,
                )
                % {"count": created}
            )
        )
