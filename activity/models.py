"""What happens on the site, who is told, what people follow and the versions they star.

None of these is a contribution: they have no revision history, are never exported, and are
deleted with the account (a star or a subscription is a personal choice).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Verb(models.TextChoices):
    VERSION_PUBLISHED = "version_published", _("a publié une version")
    STEP_CREATED = "step_created", _("a créé une étape")
    PROPOSAL_OPENED = "proposal_opened", _("a proposé des modifications")
    PROPOSAL_CLOSED = "proposal_closed", _("a examiné une proposition")
    PROPOSAL_WITHDRAWN = "proposal_withdrawn", _("a retiré une proposition")
    PROPOSAL_REVIEWED = "proposal_reviewed", _("a relu une proposition")
    COMMENT_POSTED = "comment_posted", _("a écrit un message")
    MENTIONED = "mentioned", _("vous a mentionné")
    CHALLENGE_OPENED = "challenge_opened", _("a contesté un choix")
    SOURCE_PROPOSAL_SENT = "source_proposal_sent", _("a proposé de modifier un texte source")
    SOURCE_PROPOSAL_CLOSED = "source_proposal_closed", _("a examiné une proposition sur un texte")
    MEMBER_INVITED = "member_invited", _("vous invite comme co-auteur")
    MEMBER_JOINED = "member_joined", _("est devenu co-auteur")
    MEMBER_DECLINED = "member_declined", _("a refusé l’invitation")
    TOPIC_OPENED = "topic_opened", _("a ouvert un sujet")
    TOPIC_CLOSED = "topic_closed", _("a fermé un sujet")
    TOPIC_REOPENED = "topic_reopened", _("a rouvert un sujet")
    SENTENCE_COMMENTED = "sentence_commented", _("a commenté une phrase")
    VARIANT_SET_ASIDE = "variant_set_aside", _("a écarté une variante")


class Event(models.Model):
    """Something that happened to a content; the feeds show the public ones."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("auteur"),
    )
    verb = models.CharField(_("action"), max_length=30, choices=Verb.choices)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    # The project the event belongs to, for the feed of a project.
    project = models.ForeignKey(
        "translations.TranslationProject",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
        verbose_name=_("projet"),
    )
    # Public when anyone could see the content at the time: shown in the feeds.
    is_public = models.BooleanField(_("public"), default=False)
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("événement")
        verbose_name_plural = _("événements")
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["project", "-created_at"], name="activity_event_project"),
            models.Index(fields=["actor", "-created_at"], name="activity_event_actor"),
        ]

    def __str__(self):
        return f"{self.actor} {self.get_verb_display()}"


class Notification(models.Model):
    """An event told to one person, until they read it."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("destinataire"),
    )
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="notifications", verbose_name=_("événement")
    )
    read_at = models.DateTimeField(_("lue le"), null=True, blank=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-event__created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event"], name="activity_one_notification_per_event"
            ),
        ]
        indexes = [
            models.Index(fields=["recipient", "read_at"], name="activity_notification_unread"),
        ]

    def __str__(self):
        return f"{self.recipient} · {self.event}"

    def get_absolute_url(self):
        return reverse("activity:notification", args=[self.pk])


class Subscription(models.Model):
    """A person follows a content: a project, a version, a source text, a discussion.

    An explicit unfollow is kept (``active`` false), so that contributing again does not
    subscribe the person anew.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name=_("personne"),
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    active = models.BooleanField(_("suivi"), default=True)
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("abonnement")
        verbose_name_plural = _("abonnements")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "content_type", "object_id"], name="activity_one_subscription"
            ),
        ]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="activity_subscription_target"),
        ]

    def __str__(self):
        return f"{self.user} → {self.content_type.model} {self.object_id}"


class Star(models.Model):
    """A person stars a published version, as on GitHub; only the count is public."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stars",
        verbose_name=_("personne"),
    )
    version = models.ForeignKey(
        "translations.TranslationVersion",
        on_delete=models.CASCADE,
        related_name="stars",
        verbose_name=_("version"),
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("étoile")
        verbose_name_plural = _("étoiles")
        constraints = [
            models.UniqueConstraint(fields=["user", "version"], name="activity_one_star"),
        ]

    def __str__(self):
        return f"{self.user} ★ {self.version_id}"
