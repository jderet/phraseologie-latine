from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
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


class Style(models.TextChoices):
    """The Latin a version aims at (Q4, Q41)."""

    CLASSICAL = "classical", _("classique, sans modèle particulier")
    CICERONIAN = "ciceronian", _("cicéronien")
    CAESARIAN = "caesarian", _("césarien")
    SALLUSTIAN = "sallustian", _("sallustien")
    LIVIAN = "livian", _("livien")
    SENECAN = "senecan", _("sénéquien")
    TACITEAN = "tacitean", _("tacitéen")
    PLINIAN = "plinian", _("plinien (Pline le Jeune)")
    LATE = "late", _("latin tardif et chrétien")
    HUMANIST = "humanist", _("humaniste")
    CONTEMPORARY = "contemporary", _("latin vivant contemporain")


class TranslationProject(ModeratedContent):
    """The Latin versions of one source text; its creator chooses the reference version."""

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name=_("texte source"),
    )
    title = models.CharField(_("titre"), max_length=300)
    description = models.TextField(_("description"), max_length=5000, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="translation_projects",
        verbose_name=_("créé par"),
    )
    created_at = models.DateTimeField(_("créé le"), default=timezone.now, editable=False)
    reference_version = models.ForeignKey(
        "TranslationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("version de référence"),
        help_text=_("Choisie par le créateur du projet parmi les versions publiées."),
    )

    class Meta:
        verbose_name = _("projet de traduction")
        verbose_name_plural = _("projets de traduction")
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("translations:project", args=[self.pk])


class VersionQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Published versions that are not hidden, and the user's own versions (rule 8)."""
        published = Q(state=TranslationVersion.State.PUBLISHED, is_hidden=False)
        if not user.is_authenticated:
            return self.filter(published)
        return self.filter(published | Q(author=user))


class TranslationVersion(ModeratedContent):
    """One person's Latin version of a project: a private draft until its author publishes it."""

    class State(models.TextChoices):
        DRAFT = "draft", _("brouillon")
        PUBLISHED = "published", _("publiée")

    project = models.ForeignKey(
        TranslationProject,
        on_delete=models.PROTECT,
        related_name="versions",
        verbose_name=_("projet"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="translation_versions",
        verbose_name=_("auteur"),
    )
    style = models.CharField(_("style déclaré"), max_length=20, choices=Style.choices)
    style_note = models.CharField(
        _("précision sur le style"),
        max_length=200,
        blank=True,
        help_text=_("Facultatif, par exemple : « Cicéron des lettres à Atticus »."),
    )
    state = models.CharField(
        _("état"), max_length=10, choices=State.choices, default=State.DRAFT, editable=False
    )
    created_at = models.DateTimeField(_("commencée le"), default=timezone.now, editable=False)
    published_at = models.DateTimeField(_("publiée le"), null=True, blank=True, editable=False)
    shows_draft_steps = models.BooleanField(
        _("étapes du brouillon montrées"),
        default=False,
        editable=False,
        help_text=_("Choisi une fois pour toutes à la publication."),
    )
    copied_from = models.ForeignKey(
        "VersionStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="copies",
        verbose_name=_("copiée de l’étape"),
    )

    objects = VersionQuerySet.as_manager()

    class Meta:
        verbose_name = _("version")
        verbose_name_plural = _("versions")
        ordering = ["project", "published_at", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(state="draft", published_at__isnull=True)
                | Q(state="published", published_at__isnull=False),
                name="translations_version_published_at",
            ),
        ]

    def __str__(self):
        return gettext("%(project)s, version de %(author)s") % {
            "project": self.project.title,
            "author": self.author.public_name,
        }

    def get_absolute_url(self):
        return reverse("translations:version", args=[self.pk])

    @property
    def is_published(self):
        return self.state == self.State.PUBLISHED

    @property
    def is_draft(self):
        return self.state == self.State.DRAFT


class TranslatedSegment(ModeratedContent):
    """The Latin of one sentence in the working text of a version, seen by its author only.

    Others see the text of the steps (``VersionStep``).
    """

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        related_name="segments",
        verbose_name=_("version"),
    )
    segment = models.ForeignKey(
        Segment,
        on_delete=models.PROTECT,
        related_name="translations",
        verbose_name=_("phrase source"),
    )
    text = models.TextField(_("latin"), max_length=4000, blank=True)
    # Who wrote this Latin when it is not the author of the version: the author of an accepted
    # proposal, or of a copied sentence.
    written_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("écrite par"),
    )
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        verbose_name = _("phrase traduite")
        verbose_name_plural = _("phrases traduites")
        ordering = ["version", "segment__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "segment"], name="translations_one_text_per_segment"
            ),
        ]

    def __str__(self):
        return gettext("%(version)s, phrase %(number)s") % {
            "version": self.version,
            "number": self.segment.order,
        }

    def get_absolute_url(self):
        return f"{self.version.get_absolute_url()}#phrase-{self.segment.order}"


class StepQuerySet(models.QuerySet):
    def public(self):
        """Steps anyone may see: of a published version, not hidden, and not a draft step
        unless the author chose to show them."""
        return self.filter(
            Q(during_draft=False) | Q(version__shows_draft_steps=True),
            version__state=TranslationVersion.State.PUBLISHED,
            is_hidden=False,
        )


class VersionStep(ModeratedContent):
    """A frozen state of all the sentences of a version, with a message, like a Git commit.

    Only the sentences changed since the previous step are stored (``StepSentence``).
    """

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        related_name="steps",
        verbose_name=_("version"),
    )
    number = models.PositiveIntegerField(_("numéro"), editable=False)
    message = models.CharField(
        _("message"),
        max_length=300,
        help_text=_("Ce qui a changé, par exemple : « phrases 1 à 12 revues »."),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("auteur"),
    )
    during_draft = models.BooleanField(
        _("créée pendant le brouillon"), default=False, editable=False
    )
    created_at = models.DateTimeField(_("créée le"), default=timezone.now, editable=False)

    objects = StepQuerySet.as_manager()

    class Meta:
        verbose_name = _("étape")
        verbose_name_plural = _("étapes")
        ordering = ["version", "number"]
        constraints = [
            models.UniqueConstraint(fields=["version", "number"], name="translations_step_number"),
        ]

    def __str__(self):
        return gettext("%(version)s, étape %(number)s") % {
            "version": self.version,
            "number": self.number,
        }

    def get_absolute_url(self):
        return reverse("translations:step", args=[self.version_id, self.number])


class StepSentence(models.Model):
    """The Latin of a sentence as a step changed it; empty when the sentence was erased."""

    step = models.ForeignKey(
        VersionStep,
        on_delete=models.PROTECT,
        related_name="sentences",
        verbose_name=_("étape"),
    )
    segment = models.ForeignKey(
        Segment, on_delete=models.PROTECT, related_name="+", verbose_name=_("phrase source")
    )
    text = models.TextField(_("latin"), blank=True)
    written_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("écrite par"),
    )

    class Meta:
        verbose_name = _("phrase d’une étape")
        verbose_name_plural = _("phrases d’une étape")
        ordering = ["step", "segment__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["step", "segment"], name="translations_one_text_per_step_segment"
            ),
        ]

    def __str__(self):
        return self.text


class ChangeProposal(ModeratedContent):
    """Changes proposed to the published version of someone else, like a pull request.

    The author of the version accepts or refuses each proposed sentence (Q36).
    """

    class Status(models.TextChoices):
        OPEN = "open", _("ouverte")
        CLOSED = "closed", _("close")
        WITHDRAWN = "withdrawn", _("retirée par son auteur")

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name=_("version"),
    )
    base_step = models.ForeignKey(
        VersionStep,
        on_delete=models.PROTECT,
        related_name="proposals",
        editable=False,
        verbose_name=_("étape de départ"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="change_proposals",
        verbose_name=_("auteur"),
    )
    explanation = models.TextField(
        _("explication"),
        max_length=3000,
        help_text=_("Pourquoi ces changements : tours attestés, fautes corrigées, style visé."),
    )
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.OPEN, editable=False
    )
    created_at = models.DateTimeField(_("proposée le"), default=timezone.now, editable=False)
    closed_at = models.DateTimeField(_("close le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("proposition de modifications")
        verbose_name_plural = _("propositions de modifications")
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status="open", closed_at__isnull=True)
                | (~Q(status="open") & Q(closed_at__isnull=False)),
                name="translations_proposal_closing",
            ),
        ]

    def __str__(self):
        return gettext("Proposition de %(name)s pour %(version)s") % {
            "name": self.author.public_name,
            "version": self.version,
        }

    def get_absolute_url(self):
        return reverse("translations:proposal", args=[self.pk])

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


class ProposedSentence(ModeratedContent):
    """The Latin proposed for one sentence, and the decision of the author of the version."""

    class Decision(models.TextChoices):
        PENDING = "pending", _("en attente")
        ACCEPTED = "accepted", _("acceptée")
        REFUSED = "refused", _("refusée")

    proposal = models.ForeignKey(
        ChangeProposal,
        on_delete=models.PROTECT,
        related_name="sentences",
        verbose_name=_("proposition"),
    )
    segment = models.ForeignKey(
        Segment, on_delete=models.PROTECT, related_name="+", verbose_name=_("phrase source")
    )
    base_text = models.TextField(_("latin de l’étape de départ"), blank=True, editable=False)
    text = models.TextField(_("latin proposé"), max_length=4000, blank=True)
    decision = models.CharField(
        _("décision"),
        max_length=10,
        choices=Decision.choices,
        default=Decision.PENDING,
        editable=False,
    )
    decided_at = models.DateTimeField(_("examinée le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("phrase proposée")
        verbose_name_plural = _("phrases proposées")
        ordering = ["proposal", "segment__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["proposal", "segment"], name="translations_one_proposed_text_per_segment"
            ),
        ]

    def __str__(self):
        return self.text

    def get_absolute_url(self):
        return f"{self.proposal.get_absolute_url()}#phrase-{self.segment.order}"

    @property
    def is_pending(self):
        return self.decision == self.Decision.PENDING


def version_visible_to(user, version):
    return version.is_published or is_version_author(user, version)


def is_version_author(user, version):
    return user.is_authenticated and user.pk == version.author_id


def step_visible_to(user, step):
    version = step.version
    if is_version_author(user, version):
        return True
    return version.is_published and (not step.during_draft or version.shows_draft_steps)


register(SourceText, owner_field="added_by", text_fields=("title", "author", "text"))
register(
    TranslationProject,
    owner_field="created_by",
    text_fields=("title", "description"),
    # Only the creator chooses the reference version, never a revert (T6).
    not_reverted=("reference_version",),
)
register(
    TranslationVersion,
    owner_field="author",
    text_fields=("style_note",),
    visible_to=version_visible_to,
    not_reverted=("state", "published_at", "shows_draft_steps", "copied_from"),
)
register(
    TranslatedSegment,
    owner_field="version.author",
    text_fields=("text",),
    # The working text stays private: others see the text of the steps (rule 8).
    visible_to=lambda user, translated: is_version_author(user, translated.version),
    counts_toward_limit=False,
    not_reverted=("written_by",),
)
register(
    VersionStep,
    owner_field="version.author",
    text_fields=("message",),
    visible_to=step_visible_to,
    counts_toward_limit=False,
    not_reverted=("during_draft",),
)
register(
    ChangeProposal,
    owner_field="author",
    text_fields=("explanation",),
    visible_to=lambda user, proposal: version_visible_to(user, proposal.version),
    # A revert never reopens or closes a proposal.
    not_reverted=("status", "closed_at"),
    discussion=lambda user, proposal: proposal.is_open,
)
register(
    ProposedSentence,
    owner_field="proposal.author",
    text_fields=("text",),
    visible_to=lambda user, proposed: version_visible_to(user, proposed.proposal.version),
    counts_toward_limit=False,
    not_reverted=("decision", "decided_at"),
)
