"""Messages posted in a discussion are told to those who follow the discussed content, and to the
people mentioned; the author of a message follows the discussion."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from moderation.models import Comment
from moderation.registry import owner_id

from .models import Verb
from .services import auto_follow, record


@receiver(post_save, sender=Comment, dispatch_uid="activity_comment_posted")
def comment_posted(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    discussed = instance.content_object
    if discussed is None:
        return
    auto_follow(instance.author, discussed)
    owner = owner_id(discussed)
    record(
        instance.author,
        Verb.COMMENT_POSTED,
        instance,
        recipients=[owner] if owner else [],
        mention_text=instance.text,
    )
