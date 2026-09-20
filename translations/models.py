from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from moderation.models import ModeratedContent
from moderation.registry import can_view, register

from .segmentation import MAX_LEVEL

# A work enters the public domain on the 1 January following the 70th year after its
# author's death.
COPYRIGHT_YEARS = 70

# The usual names of the levels of title, when a text does not choose its own.
DEFAULT_LEVEL_NAMES = [_("Partie"), _("Chapitre"), _("Section")]


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
    """A modern text to translate, split into sentences that may later change (``SourceChange``)."""

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
        help_text=_(
            "Une phrase par ligne ; une ligne vide entre deux paragraphes ; un titre de "
            "division sur sa ligne, précédé de #, ## ou ###."
        ),
    )
    level_names = models.CharField(
        _("noms des divisions"),
        max_length=100,
        blank=True,
        help_text=_(
            "Noms des trois niveaux de titre, séparés par des virgules : « Partie, Chapitre, "
            "Section ». Laissé vide, ces noms-là sont employés."
        ),
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="source_texts",
        verbose_name=_("ajouté par"),
    )
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)
    # The number of the latest change of its sentences (``SourceChange``); 0 as added.
    state = models.PositiveIntegerField(_("état des phrases"), default=0, editable=False)

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

    def citation(self, place):
        """« Chapitre 2, phrase 5 », or the number alone in a text without divisions."""
        if place is None:
            return ""
        if place.division is None:
            return gettext("phrase %(number)d") % {"number": place.number}
        division = gettext("%(name)s %(index)d") % {
            "name": self.level_label(place.division.level),
            "index": place.division.index,
        }
        if not place.number:
            return division
        return gettext("%(division)s, phrase %(number)d") % {
            "division": division,
            "number": place.number,
        }

    def level_label(self, level):
        """The name chosen for a level of title, or the usual one."""
        names = [name.strip() for name in self.level_names.split(",") if name.strip()]
        if 1 <= level <= len(names):
            return names[level - 1]
        return DEFAULT_LEVEL_NAMES[level - 1] if 1 <= level <= MAX_LEVEL else ""

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


class SegmentQuerySet(models.QuerySet):
    def current(self):
        """The sentences of the current text, not those a change removed."""
        return self.filter(removed_in__isnull=True)


class Segment(models.Model):
    """A sentence of a source text, never changed in place.

    A change of the text removes sentences and adds new ones (``SourceChange``); the removed
    ones stay, so that every step still shows the source text it froze.
    """

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.CASCADE,
        related_name="segments",
        verbose_name=_("texte source"),
    )
    # Sorts all the sentences ever in the text, removed ones included.
    position = models.PositiveIntegerField(_("position"), editable=False)
    # The number shown in the current text; empty once removed.
    order = models.PositiveIntegerField(_("numéro"), null=True, blank=True)
    text = models.TextField(_("phrase"))
    starts_paragraph = models.BooleanField(_("début de paragraphe"), default=False)
    # 0 for a sentence; 1 to MAX_LEVEL for the title of a part, a chapter or a section.
    level = models.PositiveSmallIntegerField(_("niveau de titre"), default=0)
    added_in = models.PositiveIntegerField(_("ajoutée au changement"), default=0, editable=False)
    removed_in = models.PositiveIntegerField(
        _("retirée au changement"), null=True, blank=True, editable=False
    )

    objects = SegmentQuerySet.as_manager()

    class Meta:
        verbose_name = _("segment")
        verbose_name_plural = _("segments")
        ordering = ["source_text", "position"]
        # Similar sentences for the translation memory, by trigrams (pg_trgm).
        indexes = [
            GinIndex(
                name="translations_segment_trigrams", fields=["text"], opclasses=["gin_trgm_ops"]
            )
        ]
        constraints = [
            # Deferred: a change renumbers the positions within its transaction.
            models.UniqueConstraint(
                fields=["source_text", "position"],
                name="translations_segment_position",
                deferrable=models.Deferrable.DEFERRED,
            ),
            models.CheckConstraint(
                condition=Q(removed_in__isnull=True, order__isnull=False)
                | Q(removed_in__isnull=False, order__isnull=True),
                name="translations_segment_order_if_current",
            ),
        ]

    def __str__(self):
        return self.text

    @cached_property
    def latest(self):
        """The sentence of the current text that carries the Latin of this one."""
        segment = self
        while segment.removed_in is not None:
            segment = (
                Segment.objects.filter(
                    source_text_id=segment.source_text_id, added_in=segment.removed_in
                )
                .order_by("position")
                .first()
            )
        return segment


class SourceChange(models.Model):
    """One change of the sentences of a source text: sentences added, edited, merged or split.

    The sentences it removes and adds are those whose ``removed_in`` or ``added_in`` is its
    number. The revision is recorded on the source text, whose split text follows.
    """

    class Kind(models.TextChoices):
        INSERT = "insert", _("ajout")
        EDIT = "edit", _("modification")
        MERGE = "merge", _("fusion")
        SPLIT = "split", _("scission")

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.PROTECT,
        related_name="changes",
        verbose_name=_("texte source"),
    )
    number = models.PositiveIntegerField(_("numéro"))
    kind = models.CharField(_("nature"), max_length=10, choices=Kind.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("auteur"),
    )
    # Who adopted the change when someone else proposed it.
    adopted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("adopté par"),
    )
    proposal = models.ForeignKey(
        "SourceProposal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="changes",
        verbose_name=_("proposition"),
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("changement du texte source")
        verbose_name_plural = _("changements du texte source")
        ordering = ["source_text", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_text", "number"], name="translations_source_change_number"
            ),
        ]

    def __str__(self):
        return gettext("%(text)s, changement %(number)s") % {
            "text": self.source_text,
            "number": self.number,
        }


class SourceProposal(ModeratedContent):
    """Changes to the sentences of a source text, proposed by someone who may not make them.

    Prepared change by change and seen by its author only, then sent with an explanation;
    whoever added the text, or a reviewer, adopts or refuses it as a whole.
    """

    class Status(models.TextChoices):
        PREPARING = "preparing", _("en préparation")
        OPEN = "open", _("ouverte")
        ADOPTED = "adopted", _("adoptée")
        REFUSED = "refused", _("refusée")
        WITHDRAWN = "withdrawn", _("retirée par son auteur")

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name=_("texte source"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="source_proposals",
        verbose_name=_("auteur"),
    )
    explanation = models.TextField(
        _("explication"),
        max_length=3000,
        blank=True,
        help_text=_(
            "Pourquoi ces changements : fautes corrigées, phrases oubliées, découpage revu."
        ),
    )
    # The changes in order, as ``sources.apply_operation`` takes them, each applying to the
    # text the previous ones left, from the state ``base_state`` of the source text.
    operations = models.JSONField(_("changements"), default=list, editable=False)
    base_state = models.PositiveIntegerField(_("état du texte de départ"), editable=False)
    status = models.CharField(
        _("statut"),
        max_length=10,
        choices=Status.choices,
        default=Status.PREPARING,
        editable=False,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("examinée par"),
    )
    created_at = models.DateTimeField(_("commencée le"), default=timezone.now, editable=False)
    sent_at = models.DateTimeField(_("envoyée le"), null=True, blank=True, editable=False)
    closed_at = models.DateTimeField(_("close le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("proposition de modification du texte")
        verbose_name_plural = _("propositions de modification du texte")
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["preparing", "open"], closed_at__isnull=True)
                | (~Q(status__in=["preparing", "open"]) & Q(closed_at__isnull=False)),
                name="translations_source_proposal_closing",
            ),
            models.UniqueConstraint(
                fields=["source_text", "author"],
                condition=Q(status="preparing"),
                name="translations_one_source_proposal_in_preparation",
            ),
        ]

    def __str__(self):
        return gettext("Proposition de %(name)s pour %(text)s") % {
            "name": self.author.public_name,
            "text": self.source_text,
        }

    def get_absolute_url(self):
        return reverse("translations:source_proposal", args=[self.pk])

    @property
    def is_preparing(self):
        return self.status == self.Status.PREPARING

    @property
    def is_open(self):
        return self.status == self.Status.OPEN


class Style(models.TextChoices):
    """The Latin a project aims at (Q4, Q41, choice of 19 September 2026)."""

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
    """The Latin translation of one source text, in one style.

    The project aims at a single text, its main version, written by its creator and the
    maintainers (the co-authors of the main version); the other versions are variants, to be
    merged or set aside (choice of 19 September 2026).
    """

    source_text = models.ForeignKey(
        SourceText,
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name=_("texte source"),
    )
    title = models.CharField(_("titre"), max_length=300)
    description = models.TextField(_("description"), max_length=5000, blank=True)
    style = models.CharField(_("style visé"), max_length=20, choices=Style.choices)
    style_note = models.CharField(
        _("précision sur le style"),
        max_length=200,
        blank=True,
        help_text=_("Facultatif, par exemple : « Cicéron des lettres à Atticus »."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="translation_projects",
        verbose_name=_("créé par"),
    )
    created_at = models.DateTimeField(_("créé le"), default=timezone.now, editable=False)
    main_version = models.OneToOneField(
        "TranslationVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("traduction principale"),
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
        """Published versions that are not hidden, and the versions the user writes: their own
        and those they co-author (rule 8)."""
        published = Q(state=TranslationVersion.State.PUBLISHED, is_hidden=False)
        if not user.is_authenticated:
            return self.filter(published)
        return self.filter(published | Q(author=user) | Q(pk__in=coauthored_by(user))).distinct()

    def written_by(self, user):
        """Versions the user writes: their own and those they co-author."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(Q(author=user) | Q(pk__in=coauthored_by(user)))


def coauthored_by(user):
    """Ids of the versions the user co-authors."""
    return VersionMember.objects.filter(user=user, status=VersionMember.Status.ACTIVE).values(
        "version_id"
    )


class TranslationVersion(ModeratedContent):
    """The main version of a project, or a variant of it: a private draft until its author
    publishes it."""

    class State(models.TextChoices):
        DRAFT = "draft", _("brouillon")
        PUBLISHED = "published", _("publiée")

    class VariantStatus(models.TextChoices):
        MAIN = "", _("traduction principale")
        OPEN = "open", _("variante ouverte")
        MERGED = "merged", _("variante fusionnée")
        SET_ASIDE = "set_aside", _("variante écartée")

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
    state = models.CharField(
        _("état"), max_length=10, choices=State.choices, default=State.DRAFT, editable=False
    )
    variant_status = models.CharField(
        _("statut de la variante"),
        max_length=10,
        choices=VariantStatus.choices,
        default=VariantStatus.OPEN,
        blank=True,
        editable=False,
    )
    closed_at = models.DateTimeField(_("close le"), null=True, blank=True, editable=False)
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
    # The step of the original up to which the copy took its changes (``copied_from`` at first).
    synced_to = models.ForeignKey(
        "VersionStep",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("mise à jour jusqu’à l’étape"),
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
            models.CheckConstraint(
                condition=Q(closed_at__isnull=True, variant_status__in=["", "open"])
                | Q(closed_at__isnull=False, variant_status__in=["merged", "set_aside"]),
                name="translations_version_closing",
            ),
        ]

    def __str__(self):
        if self.is_main:
            return self.project.title
        return gettext("%(project)s, variante de %(author)s") % {
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

    @property
    def is_main(self):
        return self.variant_status == self.VariantStatus.MAIN

    @property
    def display_name(self):
        """« Traduction principale », or « Variante de » its author."""
        if self.is_main:
            return gettext("Traduction principale")
        return gettext("Variante de %(name)s") % {"name": self.author.public_name}

    @property
    def is_open_variant(self):
        return self.variant_status == self.VariantStatus.OPEN

    @property
    def is_closed(self):
        return self.closed_at is not None


class TranslatedQuerySet(models.QuerySet):
    def current(self):
        """The working text: the sentences of the current source text.

        Those of removed sentences stay, frozen: their justifications and challenges point to them.
        """
        return self.filter(segment__removed_in__isnull=True)


class TranslatedSegment(ModeratedContent):
    """The Latin of one sentence in the working text of a version, seen by its writers only.

    Others see the text of the steps (``VersionStep``). Its status tells where the work stands,
    as in translation software: a changed sentence goes back to draft.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("brouillon")
        TRANSLATED = "translated", _("traduite")
        REVIEWED = "reviewed", _("relue")

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
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    objects = TranslatedQuerySet.as_manager()

    class Meta:
        verbose_name = _("phrase traduite")
        verbose_name_plural = _("phrases traduites")
        ordering = ["version", "segment__position"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "segment"], name="translations_one_text_per_segment"
            ),
        ]

    def __str__(self):
        return gettext("%(version)s, phrase %(number)s") % {
            "version": self.version,
            "number": self.segment.latest.order,
        }

    def get_absolute_url(self):
        return f"{self.version.get_absolute_url()}#phrase-{self.segment.latest.order}"


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
    # A name given afterwards to a step worth citing, like a release: « Édition 1 ».
    label = models.CharField(
        _("étiquette"),
        max_length=80,
        blank=True,
        help_text=_("Par exemple : « Édition 1 », « Relue par le comité »."),
    )
    # The state of the source text the step froze with the Latin (``SourceText.state``).
    source_state = models.PositiveIntegerField(_("état du texte source"), default=0, editable=False)
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
        ordering = ["step", "segment__position"]
        constraints = [
            models.UniqueConstraint(
                fields=["step", "segment"], name="translations_one_text_per_step_segment"
            ),
        ]

    def __str__(self):
        return self.text


class ChangeProposal(ModeratedContent):
    """Changes proposed to the published version of someone else, like a pull request.

    The writers of the version accept or refuse each proposed sentence (Q36). A proposal sent
    from a variant to the main version closes the variant once decided.
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
    from_version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="sent_proposals",
        verbose_name=_("variante d’origine"),
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
        ordering = ["proposal", "segment__position"]
        constraints = [
            models.UniqueConstraint(
                fields=["proposal", "segment"], name="translations_one_proposed_text_per_segment"
            ),
        ]

    def __str__(self):
        return self.text

    def get_absolute_url(self):
        return f"{self.proposal.get_absolute_url()}#proposee-{self.pk}"

    def get_discussion_url(self):
        return self.get_absolute_url()

    @property
    def is_pending(self):
        return self.decision == self.Decision.PENDING


class VersionMember(ModeratedContent):
    """A co-author of a version, invited by its author.

    A co-author writes the working text, creates steps, justifies and decides on proposals, and
    sees the draft; the author alone publishes, changes the settings and removes co-authors.
    """

    class Status(models.TextChoices):
        INVITED = "invited", _("invité")
        ACTIVE = "active", _("co-auteur")
        DECLINED = "declined", _("invitation refusée")
        REMOVED = "removed", _("retiré")

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        related_name="members",
        verbose_name=_("version"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="version_memberships",
        verbose_name=_("co-auteur"),
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("invité par"),
    )
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.INVITED, editable=False
    )
    invited_at = models.DateTimeField(_("invité le"), default=timezone.now, editable=False)
    decided_at = models.DateTimeField(_("réponse le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("co-auteur d’une version")
        verbose_name_plural = _("co-auteurs d’une version")
        ordering = ["version", "invited_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["version", "user"], name="translations_one_membership"),
        ]

    def __str__(self):
        return gettext("%(name)s, co-auteur de %(version)s") % {
            "name": self.user.public_name,
            "version": self.version,
        }

    def get_absolute_url(self):
        return reverse("translations:version_members", args=[self.version_id])

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class Topic(ModeratedContent):
    """A subject opened on a project, like an issue: a question, an error, a point of style.

    Numbered within its project (« #3 »), labelled, open or closed, discussed and supported by
    indicative votes.
    """

    class Status(models.TextChoices):
        OPEN = "open", _("ouvert")
        CLOSED = "closed", _("fermé")

    class Label(models.TextChoices):
        QUESTION = "question", _("question")
        ERROR = "error", _("erreur")
        STYLE = "style", _("style")
        SOURCE = "source", _("texte source")
        IDEA = "idea", _("idée")

    project = models.ForeignKey(
        TranslationProject,
        on_delete=models.PROTECT,
        related_name="topics",
        verbose_name=_("projet"),
    )
    number = models.PositiveIntegerField(_("numéro"), editable=False)
    title = models.CharField(_("titre"), max_length=200)
    body = models.TextField(
        _("texte"),
        max_length=5000,
        help_text=_("Écrivez #3 pour renvoyer au sujet n° 3, @Nom pour prévenir quelqu’un."),
    )
    labels = models.JSONField(_("étiquettes"), default=list, blank=True)
    segment = models.ForeignKey(
        Segment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="topics",
        verbose_name=_("phrase concernée"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="topics",
        editable=False,
        verbose_name=_("auteur"),
    )
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.OPEN, editable=False
    )
    created_at = models.DateTimeField(_("ouvert le"), default=timezone.now, editable=False)
    closed_at = models.DateTimeField(_("fermé le"), null=True, blank=True, editable=False)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name=_("fermé par"),
    )

    class Meta:
        verbose_name = _("sujet")
        verbose_name_plural = _("sujets")
        ordering = ["project", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="translations_topic_number"),
        ]

    def __str__(self):
        return f"#{self.number} {self.title}"

    def get_absolute_url(self):
        return reverse("translations:topic", args=[self.project_id, self.number])

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    def label_names(self):
        names = dict(self.Label.choices)
        return [(code, names[code]) for code in self.labels if code in names]


class GlossaryEntry(ModeratedContent):
    """A term of the glossary of a project: how a source word is rendered in Latin throughout,
    as in the termbases of translation software. Any active account proposes a term; the
    creator of the project or a reviewer adopts or rejects it."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("proposé")
        ADOPTED = "adopted", _("adopté")
        REJECTED = "rejected", _("écarté")

    project = models.ForeignKey(
        TranslationProject,
        on_delete=models.PROTECT,
        related_name="glossary",
        verbose_name=_("projet"),
    )
    source_term = models.CharField(_("terme source"), max_length=200)
    latin_term = models.CharField(_("latin"), max_length=200)
    note = models.TextField(_("note"), max_length=1000, blank=True)
    unit = models.ForeignKey(
        "phraseology.Unit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="glossary_entries",
        verbose_name=_("fiche phraséologique"),
    )
    neologism = models.ForeignKey(
        "phraseology.Neologism",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="glossary_entries",
        verbose_name=_("néologisme"),
    )
    status = models.CharField(
        _("statut"),
        max_length=10,
        choices=Status.choices,
        default=Status.PROPOSED,
        editable=False,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("proposé par"),
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name=_("décidé par"),
    )
    created_at = models.DateTimeField(_("proposé le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("terme du glossaire")
        verbose_name_plural = _("termes du glossaire")
        ordering = ["project", "source_term", "pk"]

    def __str__(self):
        return f"{self.source_term} → {self.latin_term}"

    def get_absolute_url(self):
        return f"{reverse('translations:glossary', args=[self.project_id])}#terme-{self.pk}"

    @property
    def is_adopted(self):
        return self.status == self.Status.ADOPTED


class SentenceComment(ModeratedContent):
    """A comment on one sentence of a version, as in translation software: a question, a
    remark of review. It is resolved once dealt with. On a draft, only its writers see it."""

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.PROTECT,
        related_name="sentence_comments",
        verbose_name=_("version"),
    )
    segment = models.ForeignKey(
        Segment,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("phrase source"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("auteur"),
    )
    text = models.TextField(_("commentaire"), max_length=2000)
    is_resolved = models.BooleanField(_("résolu"), default=False, editable=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name=_("résolu par"),
    )
    created_at = models.DateTimeField(_("écrit le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("commentaire d’une phrase")
        verbose_name_plural = _("commentaires des phrases")
        ordering = ["version", "segment", "created_at", "pk"]

    def __str__(self):
        return gettext("Commentaire de %(name)s") % {"name": self.author.public_name}

    def get_absolute_url(self):
        page = reverse("translations:version_comments", args=[self.version_id])
        return f"{page}#commentaire-{self.pk}"


class IgnoredAlert(models.Model):
    """A quality alert the writers of a version chose to ignore, for one Latin text: it comes
    back when the Latin changes. Working data of the version, private like its working text."""

    version = models.ForeignKey(
        TranslationVersion,
        on_delete=models.CASCADE,
        related_name="ignored_alerts",
        verbose_name=_("version"),
    )
    segment = models.ForeignKey(
        Segment, on_delete=models.CASCADE, related_name="+", verbose_name=_("phrase source")
    )
    code = models.CharField(_("vérification"), max_length=20)
    fingerprint = models.CharField(_("empreinte du latin"), max_length=16)
    ignored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("ignorée par"),
    )
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("alerte ignorée")
        verbose_name_plural = _("alertes ignorées")
        constraints = [
            models.UniqueConstraint(
                fields=["version", "segment", "code", "fingerprint"],
                name="translations_one_ignored_alert",
            ),
        ]

    def __str__(self):
        return f"{self.code} · {self.segment_id}"


class ProposalReview(ModeratedContent):
    """A review of a change proposal, as on GitHub: approve, request changes or comment.

    Indicative: the writers of the version still decide on each sentence."""

    class Verdict(models.TextChoices):
        APPROVE = "approve", _("approuve")
        CHANGES = "changes", _("demande des changements")
        COMMENT = "comment", _("commente")

    proposal = models.ForeignKey(
        ChangeProposal,
        on_delete=models.PROTECT,
        related_name="reviews",
        verbose_name=_("proposition"),
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
        verbose_name=_("relecteur"),
    )
    verdict = models.CharField(_("avis"), max_length=10, choices=Verdict.choices)
    text = models.TextField(_("commentaire"), max_length=3000, blank=True)
    created_at = models.DateTimeField(_("date"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("relecture d’une proposition")
        verbose_name_plural = _("relectures des propositions")
        ordering = ["proposal", "created_at", "pk"]

    def __str__(self):
        return gettext("%(name)s %(verdict)s") % {
            "name": self.reviewer.public_name,
            "verdict": self.get_verdict_display(),
        }

    def get_absolute_url(self):
        return f"{self.proposal.get_absolute_url()}#relecture-{self.pk}"


class PersonalMemoryEntry(models.Model):
    """A pair of one's own translation memory, imported from a TMX file: offered in the memory
    tab of the editor, to its owner only. Private like the notebook: never shown to anyone
    else, never exported, deleted with the account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memory_entries",
        verbose_name=_("personne"),
    )
    language = models.CharField(_("langue source"), max_length=8, blank=True)
    source = models.TextField(_("phrase source"), max_length=4000)
    latin = models.TextField(_("latin"), max_length=4000)
    origin = models.CharField(_("fichier"), max_length=200, blank=True)
    created_at = models.DateTimeField(_("importée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("entrée de la mémoire personnelle")
        verbose_name_plural = _("entrées de la mémoire personnelle")
        indexes = [
            GinIndex(
                name="translations_memory_trigrams", fields=["source"], opclasses=["gin_trgm_ops"]
            )
        ]

    def __str__(self):
        return self.source[:60]


def version_visible_to(user, version):
    return version.is_published or is_version_writer(user, version)


def is_version_author(user, version):
    return user.is_authenticated and user.pk == version.author_id


def version_writer_ids(version):
    """Ids of the author and the co-authors of a version."""
    return {
        version.author_id,
        *version.members.filter(status=VersionMember.Status.ACTIVE).values_list(
            "user_id", flat=True
        ),
    }


def maintainer_ids(project):
    """Ids of the creator and the maintainers of a project."""
    if project.main_version_id is None:
        return {project.created_by_id}
    return version_writer_ids(project.main_version)


def is_maintainer(user, project):
    """The creator of a project and its maintainers, the writers of its main version: they
    write the translation and decide on the variants, the glossary and the topics."""
    main = project.main_version
    return main is not None and is_version_writer(user, main)


def is_version_writer(user, version):
    """The author of a version, or one of its co-authors: they write and see the working text."""
    if not user.is_authenticated:
        return False
    if user.pk == version.author_id:
        return True
    cache = getattr(version, "_writer_ids", None)
    if cache is None:
        cache = set(
            version.members.filter(status=VersionMember.Status.ACTIVE).values_list(
                "user_id", flat=True
            )
        )
        version._writer_ids = cache
    return user.pk in cache


def source_proposal_visible_to(user, proposal):
    """A proposal never sent, even abandoned, is seen by its author only (rule 8)."""
    if proposal.sent_at is None:
        return user.is_authenticated and user.pk == proposal.author_id
    return True


def step_visible_to(user, step):
    version = step.version
    if is_version_writer(user, version):
        return True
    return version.is_published and (not step.during_draft or version.shows_draft_steps)


register(
    SourceText,
    owner_field="added_by",
    text_fields=("title", "author", "text"),
    # The sentences change only through ``SourceChange``: a revert never desynchronizes them.
    not_reverted=("text", "state"),
)
register(
    SourceProposal,
    owner_field="author",
    text_fields=("explanation",),
    visible_to=source_proposal_visible_to,
    # A revert never changes what was proposed, nor reopens or closes a proposal.
    not_reverted=("operations", "base_state", "status", "decided_by", "sent_at", "closed_at"),
    discussion=lambda user, proposal: proposal.is_open,
)
register(
    TranslationProject,
    owner_field="created_by",
    text_fields=("title", "description", "style_note"),
    # The main version is set once, at the creation of the project.
    not_reverted=("main_version",),
)
register(
    TranslationVersion,
    owner_field="author",
    visible_to=version_visible_to,
    not_reverted=(
        "state",
        "published_at",
        "shows_draft_steps",
        "copied_from",
        "synced_to",
        "variant_status",
        "closed_at",
    ),
)
register(
    TranslatedSegment,
    owner_field="version.author",
    text_fields=("text",),
    # The working text stays private: others see the text of the steps (rule 8).
    visible_to=lambda user, translated: is_version_writer(user, translated.version),
    counts_toward_limit=False,
    not_reverted=("written_by",),
)
register(
    VersionStep,
    owner_field="version.author",
    text_fields=("message", "label"),
    visible_to=step_visible_to,
    counts_toward_limit=False,
    not_reverted=("during_draft", "source_state"),
)
register(
    ChangeProposal,
    owner_field="author",
    text_fields=("explanation",),
    visible_to=lambda user, proposal: version_visible_to(user, proposal.version),
    # A revert never reopens or closes a proposal.
    not_reverted=("status", "closed_at", "from_version"),
    discussion=lambda user, proposal: proposal.is_open,
)
register(
    ProposedSentence,
    owner_field="proposal.author",
    text_fields=("text",),
    visible_to=lambda user, proposed: version_visible_to(user, proposed.proposal.version),
    counts_toward_limit=False,
    not_reverted=("decision", "decided_at"),
    # Each proposed sentence has its own thread, like the comments of a line in a review.
    discussion=lambda user, proposed: proposed.proposal.is_open,
)
register(
    VersionMember,
    owner_field="version.author",
    # The author of the version, the person invited, and the public once they co-author a
    # published version.
    visible_to=lambda user, member: (
        is_version_author(user, member.version)
        or (user.is_authenticated and user.pk == member.user_id)
        or (member.is_active and version_visible_to(user, member.version))
    ),
    not_reverted=("status", "decided_at"),
)
register(
    Topic,
    owner_field="author",
    text_fields=("title", "body"),
    visible_to=lambda user, topic: can_view(user, topic.project),
    not_reverted=("status", "closed_at", "closed_by"),
    discussion=lambda user, topic: True,
    votes=lambda user, topic: topic.is_open,
)
register(
    GlossaryEntry,
    owner_field="author",
    text_fields=("source_term", "latin_term", "note"),
    visible_to=lambda user, entry: can_view(user, entry.project),
    not_reverted=("status", "decided_by"),
)
register(
    SentenceComment,
    owner_field="author",
    text_fields=("text",),
    visible_to=lambda user, comment: version_visible_to(user, comment.version),
    not_reverted=("is_resolved", "resolved_by"),
)
register(
    ProposalReview,
    owner_field="reviewer",
    text_fields=("text",),
    visible_to=lambda user, review: version_visible_to(user, review.proposal.version),
)
