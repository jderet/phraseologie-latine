from django.contrib import admin

from .models import SourceText, TranslationProject, TranslationVersion


class ReadOnlyAdmin(admin.ModelAdmin):
    """Contributed contents change only through the site, so that each change has a revision."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceText)
class SourceTextAdmin(ReadOnlyAdmin):
    list_display = ("title", "language", "license", "added_by", "created_at", "is_hidden")
    list_filter = ("language", "license", "is_hidden")
    search_fields = ("title", "author")


@admin.register(TranslationProject)
class TranslationProjectAdmin(ReadOnlyAdmin):
    list_display = ("title", "source_text", "style", "created_by", "created_at", "is_hidden")
    list_filter = ("style", "is_hidden")
    search_fields = ("title",)


@admin.register(TranslationVersion)
class TranslationVersionAdmin(ReadOnlyAdmin):
    """Drafts are private: the admin lists versions without showing their Latin."""

    list_display = ("project", "author", "variant_status", "state", "published_at", "is_hidden")
    list_filter = ("state", "variant_status", "is_hidden")
