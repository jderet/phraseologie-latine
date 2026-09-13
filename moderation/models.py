from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ModeratedContent(models.Model):
    """Base of every contributed content: it has a history and can be hidden after a report.

    Concrete models must also be registered with ``moderation.registry.register``.
    """

    is_hidden = models.BooleanField(_("masqué"), default=False)

    class Meta:
        abstract = True


class RevisionQuerySet(models.QuerySet):
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

    objects = RevisionQuerySet.as_manager()

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
