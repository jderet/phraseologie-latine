from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ActivityConfig(AppConfig):
    name = "activity"
    verbose_name = _("Activité")

    def ready(self):
        from . import signals  # noqa: F401
