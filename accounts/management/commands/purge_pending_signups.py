from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from accounts.services import purge_pending_signups


class Command(BaseCommand):
    help = "Delete registrations whose activation link was never used (run daily)."

    def handle(self, *args, **options):
        count = purge_pending_signups()
        self.stdout.write(
            self.style.SUCCESS(
                _("Inscriptions jamais activées effacées : %(count)s") % {"count": count}
            )
        )
