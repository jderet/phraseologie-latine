from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TranslationsConfig(AppConfig):
    name = "translations"
    verbose_name = _("Traduction")
