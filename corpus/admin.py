from django.contrib import admin

from .models import AnalysisLayer, Author, Edition, Work


class ReadOnlyAdmin(admin.ModelAdmin):
    """The corpus comes from the catalogue files and the import command, not from the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Author)
class AuthorAdmin(ReadOnlyAdmin):
    list_display = ("cts_id", "name_fr", "latin_name", "abbreviation", "period")
    search_fields = ("cts_id", "name_fr", "name_en", "latin_name")


@admin.register(Work)
class WorkAdmin(ReadOnlyAdmin):
    list_display = ("cts_urn", "title", "author", "genre", "form", "is_core")
    list_filter = ("is_core", "genre", "form", "register", "author")
    search_fields = ("cts_urn", "title", "abbreviation")


@admin.register(Edition)
class EditionAdmin(ReadOnlyAdmin):
    list_display = (
        "cts_urn",
        "source_version",
        "is_current",
        "passage_count",
        "token_count",
        "imported_at",
    )
    list_filter = ("is_current",)


@admin.register(AnalysisLayer)
class AnalysisLayerAdmin(ReadOnlyAdmin):
    list_display = ("id", "tool", "tool_version", "created_at", "is_default")
