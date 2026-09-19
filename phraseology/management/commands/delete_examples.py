from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext

from phraseology.examples import ExamplesInUse, check_development, delete_examples


class Command(BaseCommand):
    help = "Delete the example units, their attestations, their history and the example accounts."

    def handle(self, *args, **options):
        check_development()
        try:
            counts = delete_examples()
        except ExamplesInUse as error:
            labels = {
                "justifications": gettext("justifications"),
                "evidences": gettext("preuves"),
                "sightings": gettext("repérages"),
                "relations": gettext("relations entre unités"),
                "abstract_words": gettext("fiches qui emploient un mot abstrait d’exemple"),
            }
            links = ", ".join(f"{labels[name]} : {count}" for name, count in error.links.items())
            raise CommandError(
                gettext(
                    "D’autres contenus renvoient aux fiches d’exemple (%(links)s) : "
                    "retirez ces liens avant de les effacer."
                )
                % {"links": links}
            ) from error
        self.stdout.write(
            self.style.SUCCESS(
                gettext(
                    "Effacé : fiches d’exemple %(units)d, attestations %(attestations)d, "
                    "autres éléments %(parts)d, mots abstraits %(abstract_words)d, "
                    "comptes d’exemple %(accounts)d ; "
                    "candidats remis à examiner %(candidates)d."
                )
                % counts
            )
        )
