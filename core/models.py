from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _


class GuideVersion(models.Model):
    """A dated version of the annotation guide (Q54).

    A version never changes: publishing the guide again makes a new version, and every version
    stays readable.
    """

    number = models.PositiveIntegerField(_("version"), unique=True, editable=False)
    text = models.TextField(
        _("texte"),
        max_length=100_000,
        help_text=_(
            "Une ligne « ## Titre » ou « ### Titre » fait un intertitre ; les lignes qui "
            "commencent par « - » font une liste ; une ligne vide sépare les paragraphes."
        ),
    )
    summary = models.CharField(
        _("ce qui change"),
        max_length=300,
        blank=True,
        help_text=_("Facultatif : ce que cette version change par rapport à la précédente."),
    )
    published_at = models.DateTimeField(_("publiée le"), default=timezone.now, editable=False)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("publiée par"),
    )

    class Meta:
        verbose_name = _("version du guide d’annotation")
        verbose_name_plural = _("versions du guide d’annotation")
        ordering = ["-number"]

    def __str__(self):
        return gettext("Guide d’annotation, version %(number)d") % {"number": self.number}

    def get_absolute_url(self):
        return reverse("core:guide_version", args=[self.number])
