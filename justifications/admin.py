from django.contrib import admin

from .models import BibliographicWork


@admin.register(BibliographicWork)
class BibliographicWorkAdmin(admin.ModelAdmin):
    """Administrators keep the list of cited works; a cited work is never deleted."""

    list_display = ("abbreviation", "title", "kind", "rights")
    list_filter = ("kind", "rights")
    search_fields = ("abbreviation", "title")

    def has_delete_permission(self, request, obj=None):
        return False
