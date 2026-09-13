from django.contrib import admin

from .models import SourceText


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
