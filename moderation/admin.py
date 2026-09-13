from django.contrib import admin

from .models import Comment, Report, Revision, Vote


class ReadOnlyAdmin(admin.ModelAdmin):
    """History and reports are changed only through the moderation services."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Revision)
class RevisionAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "content_type", "object_id", "action", "author")
    list_filter = ("action", "content_type")
    date_hierarchy = "created_at"


@admin.register(Report)
class ReportAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "reason", "status", "content_type", "object_id", "author")
    list_filter = ("status", "reason")
    date_hierarchy = "created_at"


@admin.register(Comment)
class CommentAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "content_type", "object_id", "author", "is_hidden")
    list_filter = ("is_hidden", "content_type")
    date_hierarchy = "created_at"


@admin.register(Vote)
class VoteAdmin(ReadOnlyAdmin):
    list_display = ("updated_at", "content_type", "object_id", "author", "value")
    list_filter = ("value", "content_type")
