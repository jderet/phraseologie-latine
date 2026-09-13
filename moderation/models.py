from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .registry import can_view, register


class ModeratedContent(models.Model):
    """Base of every contributed content: it has a history and can be hidden after a report.

    Concrete models must also be registered with ``moderation.registry.register``.
    """

    is_hidden = models.BooleanField(_("masqué"), default=False)

    class Meta:
        abstract = True


class ObjectQuerySet(models.QuerySet):
    """Records attached to a content: revisions, messages."""

    def for_object(self, obj):
        return self.filter(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk)


class Revision(models.Model):
    """One recorded change of a contributed content, with its full state before and after."""

    class Action(models.TextChoices):
        CREATE = "create", _("création")
        UPDATE = "update", _("modification")
        REVERT = "revert", _("retour à une version précédente")
        HIDE = "hide", _("masquage")
        UNHIDE = "unhide", _("rétablissement")

    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, verbose_name=_("type de contenu")
    )
    object_id = models.PositiveBigIntegerField(_("identifiant du contenu"))
    content_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revisions",
        verbose_name=_("auteur"),
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)
    action = models.CharField(_("action"), max_length=10, choices=Action.choices)
    before = models.JSONField(_("état avant"), null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(_("état après"), encoder=DjangoJSONEncoder)
    comment = models.CharField(_("commentaire"), max_length=300, blank=True)
    reverted_to = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("version rétablie"),
    )

    objects = ObjectQuerySet.as_manager()

    class Meta:
        verbose_name = _("révision")
        verbose_name_plural = _("révisions")
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "created_at"],
                name="moderation_revision_object",
            ),
            models.Index(fields=["author", "created_at"], name="moderation_revision_author"),
        ]

    def __str__(self):
        return f"{self.content_type.name} {self.object_id} · {self.get_action_display()}"

    def changes(self):
        """Fields whose value differs from the previous state, with their labels."""
        model = self.content_type.model_class()
        before = self.before or {}
        rows = []
        for name, value in self.after.items():
            if self.before is not None and before.get(name) == value:
                continue
            try:
                label = model._meta.get_field(name).verbose_name
            except (AttributeError, FieldDoesNotExist):
                label = name
            rows.append({"name": name, "label": label, "before": before.get(name), "after": value})
        return rows


class Report(models.Model):
    """A report on a contributed content, handled by reviewers and administrators."""

    class Reason(models.TextChoices):
        ILLEGAL = "illegal", _("contenu manifestement illicite")
        ABUSE = "abuse", _("propos injurieux ou harcèlement")
        COPYRIGHT = "copyright", _("atteinte au droit d’auteur")
        SPAM = "spam", _("publicité ou spam")
        ERROR = "error", _("erreur manifeste")
        OTHER = "other", _("autre motif")

    class Status(models.TextChoices):
        OPEN = "open", _("ouvert")
        HANDLED = "handled", _("traité")
        REJECTED = "rejected", _("rejeté")

    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, verbose_name=_("type de contenu")
    )
    object_id = models.PositiveBigIntegerField(_("identifiant du contenu"))
    content_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reports",
        verbose_name=_("auteur"),
    )
    reason = models.CharField(_("motif"), max_length=20, choices=Reason.choices)
    message = models.TextField(_("précisions"), max_length=2000, blank=True)
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.OPEN
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("traité par"),
    )
    handled_at = models.DateTimeField(_("traité le"), null=True, blank=True)
    resolution = models.TextField(_("suite donnée"), max_length=2000, blank=True)

    class Meta:
        verbose_name = _("signalement")
        verbose_name_plural = _("signalements")
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["status", "created_at"], name="moderation_report_status")]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "content_type", "object_id"],
                condition=Q(status="open"),
                name="moderation_one_open_report_per_author",
            ),
        ]

    def __str__(self):
        return f"{self.get_reason_display()} · {self.content_type.name} {self.object_id}"


class Comment(ModeratedContent):
    """A message in the discussion of a content (Q48); the thread is the list of its messages."""

    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, verbose_name=_("type de contenu")
    )
    object_id = models.PositiveBigIntegerField(_("identifiant du contenu"))
    content_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comments",
        verbose_name=_("auteur"),
    )
    text = models.TextField(_("message"), max_length=5000)
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    objects = ObjectQuerySet.as_manager()

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["content_type", "object_id", "created_at"],
                name="moderation_comment_object",
            ),
        ]

    def __str__(self):
        return gettext("Message de %(author)s") % {"author": self.author.public_name}

    def get_absolute_url(self):
        target = self.content_object
        return f"{target.get_absolute_url()}#message-{self.pk}"


class Vote(models.Model):
    """An indicative opinion on a content. A vote is not a content: it has no history."""

    class Value(models.IntegerChoices):
        FOR = 1, _("pour")
        AGAINST = -1, _("contre")

    content_type = models.ForeignKey(
        ContentType, on_delete=models.PROTECT, verbose_name=_("type de contenu")
    )
    object_id = models.PositiveBigIntegerField(_("identifiant du contenu"))
    content_object = GenericForeignKey("content_type", "object_id")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="votes",
        verbose_name=_("auteur"),
    )
    value = models.SmallIntegerField(_("avis"), choices=Value.choices)
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        verbose_name = _("vote")
        verbose_name_plural = _("votes")
        constraints = [
            models.UniqueConstraint(
                fields=["author", "content_type", "object_id"],
                name="moderation_one_vote_per_author",
            ),
            models.CheckConstraint(condition=Q(value__in=[1, -1]), name="moderation_vote_value"),
        ]

    def __str__(self):
        return f"{self.get_value_display()} · {self.content_type.name} {self.object_id}"


register(
    Comment,
    owner_field="author",
    text_fields=("text",),
    visible_to=lambda user, comment: (
        comment.content_object is not None and can_view(user, comment.content_object)
    ),
)
