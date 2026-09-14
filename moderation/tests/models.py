"""A content model that exists only in tests, to exercise moderation before real contents.

It has no migration: its table is created once the test database is migrated, whatever the
order of the tests, since deleting a user in any test looks for notes pointing to that user.
"""

from django.conf import settings
from django.db import connections, models
from django.db.models.signals import post_migrate

from moderation.models import ModeratedContent
from moderation.registry import register


class ModerationTestNote(ModeratedContent):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    text = models.TextField("texte")
    is_draft = models.BooleanField(default=False)

    class Meta:
        app_label = "moderation"

    def __str__(self):
        return self.text

    def get_absolute_url(self):
        return f"/notes/{self.pk}/"


def drafts_visible_to_their_author(user, note):
    return not note.is_draft or (user.is_authenticated and user.pk == note.author_id)


register(
    ModerationTestNote,
    owner_field="author",
    text_fields=("text",),
    visible_to=drafts_visible_to_their_author,
)


def create_note_table(sender=None, using="default", **kwargs):
    """Create the table of the test-only model in the database just migrated, if missing."""
    connection = connections[using]
    if ModerationTestNote._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(ModerationTestNote)


post_migrate.connect(create_note_table, dispatch_uid="moderation_test_note_table")
