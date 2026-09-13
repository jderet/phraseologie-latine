from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from corpus.models import Passage, Token
from moderation.models import ModeratedContent
from moderation.registry import register
from translations.models import TranslatedSegment, version_visible_to


class BibliographicWork(models.Model):
    """A grammar or a dictionary, cited by reference only: nothing of it is copied (rule 12)."""

    class Kind(models.TextChoices):
        GRAMMAR = "grammar", _("grammaire")
        DICTIONARY = "dictionary", _("dictionnaire")

    class Rights(models.TextChoices):
        FREE = "free", _("libre de droits")
        RESTRICTED = "restricted", _("sous droits : cité seulement")

    abbreviation = models.CharField(_("abréviation"), max_length=30, unique=True)
    title = models.CharField(_("titre"), max_length=300)
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    rights = models.CharField(
        _("droits"), max_length=20, choices=Rights.choices, default=Rights.RESTRICTED
    )

    class Meta:
        verbose_name = _("ouvrage de référence")
        verbose_name_plural = _("ouvrages de référence")
        ordering = ["abbreviation"]

    def __str__(self):
        return f"{self.abbreviation} – {self.title}"


class Strength(models.IntegerChoices):
    """The scale of evidence strength (Q45), from the strongest to the weakest."""

    ATTESTED = 1, _("attesté tel quel en prose classique")
    VARIANT = 2, _("attesté avec variante")
    MARGINAL = 3, _("attesté seulement en poésie ou à basse époque")
    ANALOGY = 4, _("par analogie")
    NOT_FOUND = 5, _("introuvable dans le corpus")


ATTESTED_STRENGTHS = {Strength.ATTESTED, Strength.VARIANT, Strength.MARGINAL}


class Justification(ModeratedContent):
    """Evidence for some Latin words of a translated sentence.

    The justified words are kept as they were written: when the sentence no longer contains
    them, the justification is to be reviewed (rule 6).
    """

    translated_segment = models.ForeignKey(
        TranslatedSegment,
        on_delete=models.PROTECT,
        related_name="justifications",
        verbose_name=_("phrase traduite"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="justifications",
        verbose_name=_("auteur"),
    )
    latin_excerpt = models.CharField(
        _("passage latin justifié"),
        max_length=500,
        help_text=_("Les mots de votre phrase latine que vous justifiez, tels quels."),
    )
    latin_start = models.PositiveIntegerField(_("position du passage"), default=0)
    source_excerpt = models.CharField(
        _("passage du texte source"),
        max_length=500,
        blank=True,
        help_text=_("Facultatif : les mots du texte source que ce passage traduit."),
    )
    strength = models.PositiveSmallIntegerField(
        _("force de preuve"),
        choices=Strength.choices,
        help_text=_("De la plus forte (1) à la plus faible (5)."),
    )
    comment = models.TextField(
        _("commentaire"),
        max_length=3000,
        blank=True,
        help_text=_("Obligatoire pour une justification par analogie."),
    )
    corpus_version = models.CharField(
        _("version du corpus interrogé"),
        max_length=200,
        blank=True,
        help_text=_("Enregistrée quand le passage est introuvable dans le corpus (règle 7)."),
    )
    created_at = models.DateTimeField(_("créée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("justification")
        verbose_name_plural = _("justifications")
        ordering = ["translated_segment", "latin_start", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(strength__gte=1, strength__lte=5),
                name="justifications_strength_scale",
            ),
            models.CheckConstraint(
                condition=~Q(strength=4) | ~Q(comment=""),
                name="justifications_analogy_has_comment",
                violation_error_message=_("Une justification par analogie exige un commentaire."),
            ),
            models.CheckConstraint(
                condition=~Q(strength=5) | ~Q(corpus_version=""),
                name="justifications_not_found_has_corpus_version",
            ),
        ]

    def __str__(self):
        return gettext("Justification de « %(excerpt)s »") % {"excerpt": self.latin_excerpt}

    def get_absolute_url(self):
        return reverse("justifications:detail", args=[self.pk])

    def locate(self):
        """(start, end) of the justified words in the current Latin, or None if they changed.

        Words that only moved in the sentence are found again when they occur once.
        """
        text = self.translated_segment.text
        end = self.latin_start + len(self.latin_excerpt)
        if text[self.latin_start : end] == self.latin_excerpt:
            return self.latin_start, end
        if text.count(self.latin_excerpt) == 1:
            start = text.index(self.latin_excerpt)
            return start, start + len(self.latin_excerpt)
        return None

    @property
    def needs_review(self):
        return self.locate() is None


class Evidence(ModeratedContent):
    """One piece of evidence: words of the corpus, or a place in a grammar or a dictionary."""

    class Kind(models.TextChoices):
        CORPUS = "corpus", _("attestation du corpus")
        GRAMMAR = "grammar", _("règle de grammaire")
        DICTIONARY = "dictionary", _("article de dictionnaire")

    justification = models.ForeignKey(
        Justification,
        on_delete=models.PROTECT,
        related_name="evidences",
        verbose_name=_("justification"),
    )
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices)
    passage = models.ForeignKey(
        Passage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("passage"),
    )
    # Stable word identifiers (rule 1); their order is their position in the edition.
    tokens = models.ManyToManyField(
        Token, blank=True, related_name="+", verbose_name=_("mots cités")
    )
    work = models.ForeignKey(
        BibliographicWork,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidences",
        verbose_name=_("ouvrage"),
    )
    locator = models.CharField(
        _("localisation"),
        max_length=100,
        blank=True,
        help_text=_("Paragraphe, page ou entrée : « § 426 », « s. v. consilium »."),
    )
    note = models.CharField(_("note"), max_length=300, blank=True)
    is_withdrawn = models.BooleanField(_("retirée"), default=False)
    created_at = models.DateTimeField(_("ajoutée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("preuve")
        verbose_name_plural = _("preuves")
        ordering = ["justification", "created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="corpus", passage__isnull=False, work__isnull=True)
                | (
                    ~Q(kind="corpus") & Q(passage__isnull=True, work__isnull=False) & ~Q(locator="")
                ),
                name="justifications_evidence_kind",
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.CORPUS:
            return str(self.passage)
        return f"{self.work.abbreviation} {self.locator}"


def justification_visible_to(user, justification):
    return version_visible_to(user, justification.translated_segment.version)


register(
    Justification,
    owner_field="author",
    text_fields=("source_excerpt", "comment"),
    visible_to=justification_visible_to,
)
register(
    Evidence,
    owner_field="justification.author",
    text_fields=("locator", "note"),
    visible_to=lambda user, evidence: justification_visible_to(user, evidence.justification),
    counts_toward_limit=False,
)
