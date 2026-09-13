"""A content model that exists only in tests, to exercise moderation before real contents.

Its table is created by ``ModerationTestCase``; it has no migration.
"""

from django.conf import settings
from django.db import models

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
