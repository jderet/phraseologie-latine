from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from corpus.models import Passage, Token
from moderation.models import ModeratedContent
from moderation.registry import can_view, register
from translations.models import TranslatedSegment, is_version_writer, version_visible_to


def locate_excerpt(text, excerpt, start):
    """(start, end) of words in a Latin sentence, or None when the sentence no longer has them.

    Words that only moved in the sentence are found again when they occur once.
    """
    end = start + len(excerpt)
    if text[start:end] == excerpt:
        return start, end
    if text.count(excerpt) == 1:
        found = text.index(excerpt)
        return found, found + len(excerpt)
    return None


def shown_latin(obj):
    """The Latin a justification or a challenge is read against.

    Views set ``shown_text``, the sentence as the reader sees it (the working text for the
    author of the version, the text of a step for others); without it, the working text.
    """
    text = getattr(obj, "shown_text", None)
    return obj.translated_segment.text if text is None else text


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
    units = models.ManyToManyField(
        "phraseology.Unit",
        blank=True,
        related_name="justifications",
        verbose_name=_("fiches phraséologiques citées"),
    )
    # The step that brought the justification out: others see it only from then on.
    step = models.ForeignKey(
        "translations.VersionStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="justifications",
        verbose_name=_("étape de parution"),
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
        """(start, end) of the justified words in the Latin shown, or None if they changed."""
        return locate_excerpt(shown_latin(self), self.latin_excerpt, self.latin_start)

    @property
    def needs_review(self):
        return self.locate() is None

    @property
    def is_challenged(self):
        """Whether an open challenge contests this justification."""
        open_challenges = getattr(self, "open_challenges", None)
        if open_challenges is None:
            return self.challenges.filter(status=Challenge.Status.OPEN, is_hidden=False).exists()
        return bool(open_challenges)


class Evidence(ModeratedContent):
    """One piece of evidence: words of the corpus, or a place in a grammar or a dictionary.

    It supports a justification, a challenge as a counter-example, or a neologism.
    """

    class Kind(models.TextChoices):
        CORPUS = "corpus", _("attestation du corpus")
        GRAMMAR = "grammar", _("règle de grammaire")
        DICTIONARY = "dictionary", _("article de dictionnaire")

    justification = models.ForeignKey(
        Justification,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidences",
        verbose_name=_("justification"),
    )
    challenge = models.ForeignKey(
        "Challenge",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidences",
        verbose_name=_("contestation"),
    )
    neologism = models.ForeignKey(
        "phraseology.Neologism",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidences",
        verbose_name=_("néologisme"),
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
    attestation = models.ForeignKey(
        "phraseology.Attestation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="evidences",
        verbose_name=_("attestation d’une fiche"),
    )
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
            models.CheckConstraint(
                condition=Q(
                    justification__isnull=False, challenge__isnull=True, neologism__isnull=True
                )
                | Q(justification__isnull=True, challenge__isnull=False, neologism__isnull=True)
                | Q(justification__isnull=True, challenge__isnull=True, neologism__isnull=False),
                name="justifications_evidence_one_parent",
            ),
        ]

    def __str__(self):
        if self.kind == self.Kind.CORPUS:
            return str(self.passage)
        return f"{self.work.abbreviation} {self.locator}"


def justification_visible_to(user, justification):
    """Others see a justification once a step of the published version has brought it out."""
    version = justification.translated_segment.version
    if is_version_writer(user, version):
        return True
    return version.is_published and justification.step_id is not None


register(
    Justification,
    owner_field="author",
    text_fields=("source_excerpt", "comment"),
    visible_to=justification_visible_to,
    not_reverted=("step",),
)


class Challenge(ModeratedContent):
    """A contested translation choice: argument, counter-examples, votes and discussion (Q48)."""

    class Status(models.TextChoices):
        OPEN = "open", _("ouverte")
        UPHELD = "upheld", _("retenue")
        DISMISSED = "dismissed", _("écartée")
        WITHDRAWN = "withdrawn", _("retirée par son auteur")

    translated_segment = models.ForeignKey(
        TranslatedSegment,
        on_delete=models.PROTECT,
        related_name="challenges",
        verbose_name=_("phrase traduite"),
    )
    justification = models.ForeignKey(
        Justification,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="challenges",
        verbose_name=_("justification contestée"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="challenges",
        verbose_name=_("auteur"),
    )
    latin_excerpt = models.CharField(
        _("passage contesté"),
        max_length=500,
        help_text=_("Les mots contestés, tels qu’ils sont écrits."),
    )
    latin_start = models.PositiveIntegerField(_("position du passage"), default=0)
    step = models.ForeignKey(
        "translations.VersionStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="challenges",
        verbose_name=_("étape contestée"),
    )
    argument = models.TextField(
        _("argument"),
        max_length=5000,
        help_text=_("Pourquoi ce choix vous paraît fautif, et ce que vous proposez à la place."),
    )
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.OPEN, editable=False
    )
    resolution = models.TextField(
        _("décision motivée"), max_length=3000, blank=True, editable=False
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("close par"),
    )
    closed_at = models.DateTimeField(_("close le"), null=True, blank=True, editable=False)
    created_at = models.DateTimeField(_("ouverte le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("contestation")
        verbose_name_plural = _("contestations")
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status="open", closed_at__isnull=True, closed_by__isnull=True)
                | (~Q(status="open") & Q(closed_at__isnull=False, closed_by__isnull=False)),
                name="justifications_challenge_closing",
            ),
        ]

    def __str__(self):
        return gettext("Contestation de « %(excerpt)s »") % {"excerpt": self.latin_excerpt}

    def get_absolute_url(self):
        return reverse("justifications:challenge", args=[self.pk])

    def locate(self):
        return locate_excerpt(shown_latin(self), self.latin_excerpt, self.latin_start)

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def contested_author_id(self):
        return self.translated_segment.version.author_id


def evidence_visible_to(user, evidence):
    if evidence.neologism_id:
        return can_view(user, evidence.neologism)
    if evidence.justification_id:
        return justification_visible_to(user, evidence.justification)
    return version_visible_to(user, evidence.challenge.translated_segment.version)


def evidence_owner_id(evidence):
    if evidence.neologism_id:
        return evidence.neologism.created_by_id
    return (evidence.justification or evidence.challenge).author_id


register(
    Evidence,
    owner_field=evidence_owner_id,
    text_fields=("locator", "note"),
    visible_to=evidence_visible_to,
    counts_toward_limit=False,
)
register(
    Challenge,
    owner_field="author",
    text_fields=("argument",),
    visible_to=lambda user, challenge: version_visible_to(
        user, challenge.translated_segment.version
    ),
    # A revert never reopens or closes a challenge.
    not_reverted=("status", "resolution", "closed_by", "closed_at"),
    discussion=lambda user, challenge: challenge.is_open,
    votes=lambda user, challenge: challenge.is_open and user.pk != challenge.contested_author_id,
)
