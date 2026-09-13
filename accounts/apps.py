from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = _("Comptes")

    def ready(self):
        from .roles import sync_roles

        post_migrate.connect(sync_roles, dispatch_uid="accounts.roles.sync_roles")
