from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from moderation.models import ModeratedContent
from moderation.registry import register

# A work enters the public domain on the 1 January following the 70th year after its
# author's death.
COPYRIGHT_YEARS = 70


def last_public_domain_death_year(today=None):
    """Latest year of death whose authors' works are in the public domain today."""
    today = today or timezone.localdate()
    return today.year - COPYRIGHT_YEARS - 1


class Language(models.TextChoices):
    FRENCH = "fr", _("français")
    ENGLISH = "en", _("anglais")
    GERMAN = "de", _("allemand")
    ITALIAN = "it", _("italien")
    SPANISH = "es", _("espagnol")


class License(models.TextChoices):
    """Licenses compatible with translations published under CC BY-SA 4.0."""

    PUBLIC_DOMAIN = "public-domain", _("domaine public")
    CC0 = "cc0-1.0", "CC0 1.0"
    CC_BY_4 = "cc-by-4.0", "CC BY 4.0"
    CC_BY_3 = "cc-by-3.0", "CC BY 3.0"
    CC_BY_SA_4 = "cc-by-sa-4.0", "CC BY-SA 4.0"
    CC_BY_SA_3 = "cc-by-sa-3.0", "CC BY-SA 3.0"


LICENSE_URLS = {
    License.CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    License.CC_BY_4: "https://creativecommons.org/licenses/by/4.0/",
    License.CC_BY_3: "https://creativecommons.org/licenses/by/3.0/",
    License.CC_BY_SA_4: "https://creativecommons.org/licenses/by-sa/4.0/",
    License.CC_BY_SA_3: "https://creativecommons.org/licenses/by-sa/3.0/",
}


class SourceText(ModeratedContent):
    """A modern text to translate, split into sentences once and for all when it is added."""

    title = models.CharField(_("titre"), max_length=300)
    author = models.CharField(
        _("auteur du texte"),
        max_length=200,
        blank=True,
        help_text=_("Pour un article de Wikipédia : « contributeurs de Wikipédia »."),
    )
    author_death_year = models.IntegerField(
        _("année de mort de l’auteur"),
        null=True,
        blank=True,
        help_text=_(
            "Obligatoire pour un texte du domaine public ; pour une œuvre anonyme, année de "
            "publication."
        ),
    )
    language = models.CharField(_("langue"), max_length=2, choices=Language.choices)
    source_url = models.URLField(
        _("adresse d’origine"),
        max_length=500,
        blank=True,
        help_text=_(
            "Obligatoire pour un texte sous licence libre, qui demande de citer sa source."
        ),
    )
    license = models.CharField(_("licence"), max_length=20, choices=License.choices)
    text = models.TextField(
        _("texte découpé"),
        help_text=_("Une phrase par ligne ; une ligne vide entre deux paragraphes."),
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="source_texts",
        verbose_name=_("ajouté par"),
    )
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("texte source")
        verbose_name_plural = _("textes sources")
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(license="public-domain") | Q(author_death_year__isnull=False),
                name="translations_public_domain_has_death_year",
            ),
            models.CheckConstraint(
                condition=Q(license="public-domain") | ~Q(source_url=""),
                name="translations_free_license_has_source_url",
            ),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("translations:source", args=[self.pk])

    def clean(self):
        super().clean()
        errors = {}
        if self.license == License.PUBLIC_DOMAIN:
            last_year = last_public_domain_death_year()
            if self.author_death_year is None:
                errors["author_death_year"] = _(
                    "Indiquez l’année de mort de l’auteur : un texte n’entre dans le domaine "
                    "public que 70 ans après."
                )
            elif self.author_death_year > last_year:
                errors["author_death_year"] = _(
                    "Ce texte n’est pas dans le domaine public : seuls le sont les textes des "
                    "auteurs morts en %(year)s ou avant."
                ) % {"year": last_year}
        elif self.license and not self.source_url:
            errors["source_url"] = _(
                "Indiquez l’adresse d’origine : une licence libre demande de citer la source."
            )
        if errors:
            raise ValidationError(errors)

    @property
    def is_public_domain(self):
        return self.license == License.PUBLIC_DOMAIN

    @property
    def legal_status(self):
        return _("domaine public") if self.is_public_domain else _("licence libre")

    @property
    def license_url(self):
        return LICENSE_URLS.get(self.license, "")


class Segment(models.Model):
    """A sentence of a source text; it never changes once the text is added."""

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.CASCADE,
        related_name="segments",
        verbose_name=_("texte source"),
    )
    order = models.PositiveIntegerField(_("numéro"))
    text = models.TextField(_("phrase"))
    starts_paragraph = models.BooleanField(_("début de paragraphe"), default=False)

    class Meta:
        verbose_name = _("segment")
        verbose_name_plural = _("segments")
        ordering = ["source_text", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_text", "order"], name="translations_segment_order"
            ),
        ]

    def __str__(self):
        return self.text


register(SourceText, owner_field="added_by", text_fields=("title", "author", "text"))
