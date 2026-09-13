from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CorpusConfig(AppConfig):
    name = "corpus"
    verbose_name = _("Corpus")
