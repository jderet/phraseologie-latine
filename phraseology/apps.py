from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PhraseologyConfig(AppConfig):
    name = "phraseology"
    verbose_name = _("Phraséologie")
