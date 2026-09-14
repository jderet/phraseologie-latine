from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .forms import AdminLoginForm
from .models import User

# The admin login counts failed attempts like the site's.
admin.site.login_form = AdminLoginForm


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Profil"), {"fields": ("display_name", "orcid", "interface_language")}),
        (
            _("Statut"),
            {
                "fields": (
                    "is_active",
                    "is_confirmed",
                    "is_adult",
                    "adult_declared_at",
                    "anonymized_at",
                )
            },
        ),
        (
            _("Permissions"),
            {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "display_name", "usable_password", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("adult_declared_at", "anonymized_at", "last_login", "date_joined")
    list_display = ("email", "display_name", "is_active", "is_confirmed", "is_staff")
    list_filter = ("is_active", "is_confirmed", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "display_name")
    ordering = ("email",)
