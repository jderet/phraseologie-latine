from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext, ngettext

from accounts.roles import is_administrator
from phraseology.models import Unit
from phraseology.schema import format_schema, writes_case
from phraseology.services import convert_schema


class Command(BaseCommand):
    help = (
        "Write again the schemas whose prepositional phrases are written as Universal "
        "Dependencies writes them, with the preposition first; each change is a revision."
    )

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="The administrator the changes are by.")
        parser.add_argument(
            "--dry-run", action="store_true", help="List the schemas without changing them."
        )

    def handle(self, *args, email="", dry_run=False, **options):
        user = None
        if not dry_run:
            user = get_user_model().objects.filter(email__iexact=email).first() if email else None
            if user is None or not is_administrator(user):
                raise CommandError(
                    gettext("Indiquez l’adresse d’un compte administrateur : --email.")
                )
        count = 0
        units = Unit.objects.filter(schema__icontains="case").order_by("pk")
        for unit in units.iterator():
            if not writes_case(unit.schema):
                continue
            try:
                written = format_schema(unit.edges)
            except ValidationError:
                self.stderr.write(
                    gettext("Schéma illisible, laissé tel quel : %(unit)s (%(pk)d).")
                    % {"unit": unit.reference_form, "pk": unit.pk}
                )
                continue
            if written == unit.schema:
                continue
            self.stdout.write(f"{unit.pk} · {unit.reference_form} : {unit.schema} → {written}")
            if not dry_run:
                convert_schema(unit, user)
            count += 1
        if dry_run:
            message = ngettext(
                "%(count)d schéma à convertir.", "%(count)d schémas à convertir.", count
            )
        else:
            message = ngettext("%(count)d schéma converti.", "%(count)d schémas convertis.", count)
        self.stdout.write(self.style.SUCCESS(message % {"count": count}))
