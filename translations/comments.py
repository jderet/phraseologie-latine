"""Comments on the sentences of a version. Its writers always comment; others, once the version
is published. The writers and the author of a comment mark it resolved."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext

from activity.models import Verb
from activity.services import record
from moderation.registry import can_view
from moderation.services import save_with_revision

from .models import SentenceComment, is_version_writer, version_writer_ids


def can_comment_sentence(user, version):
    if not (user.is_authenticated and user.is_active) or version.is_hidden:
        return False
    return is_version_writer(user, version) or version.is_published


def can_resolve(user, comment):
    return user.is_authenticated and (
        user.pk == comment.author_id or is_version_writer(user, comment.version)
    )


@transaction.atomic
def post_sentence_comment(version, segment, author, text):
    if not can_comment_sentence(author, version):
        raise PermissionDenied
    if segment.source_text_id != version.project.source_text_id:
        raise ValueError("The sentence does not belong to the text of the version.")
    text = (text or "").strip()
    if not text:
        raise ValidationError(gettext("Écrivez un commentaire."), code="empty")
    comment = SentenceComment(version=version, segment=segment, author=author, text=text)
    save_with_revision(comment, author)
    earlier = set(
        SentenceComment.objects.filter(version=version, segment=segment).values_list(
            "author_id", flat=True
        )
    )
    record(
        author,
        Verb.SENTENCE_COMMENTED,
        comment,
        recipients=version_writer_ids(version) | earlier,
        mention_text=text,
    )
    return comment


@transaction.atomic
def set_resolved(comment, user, resolved):
    comment = (
        SentenceComment.objects.select_for_update().select_related("version").get(pk=comment.pk)
    )
    if not can_resolve(user, comment):
        raise PermissionDenied
    if comment.is_resolved == resolved:
        return None
    comment.is_resolved = resolved
    comment.resolved_by = user if resolved else None
    label = gettext("Résolu") if resolved else gettext("Rouvert")
    return save_with_revision(comment, user, comment=label)


def comments_for(user, version, segment=None):
    queryset = SentenceComment.objects.filter(version=version).select_related(
        "author", "resolved_by", "segment"
    )
    if segment is not None:
        queryset = queryset.filter(segment=segment)
    shown = []
    for comment in queryset:
        comment.version = version
        if can_view(user, comment):
            shown.append(comment)
    return shown


def open_counts(user, version):
    """{segment id: number of unresolved comments} the user may see."""
    counts = {}
    for comment in comments_for(user, version):
        if not comment.is_resolved:
            counts[comment.segment_id] = counts.get(comment.segment_id, 0) + 1
    return counts
