from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from corpus.models import AnalysisLayer, Passage, Token, Work
from justifications.models import BibliographicWork
from moderation.models import ModeratedContent
from moderation.registry import can_view, register
from translations.models import Language

from .schema import parse_schema


class Kind(models.TextChoices):
    """Provisional closed typology (Q10, Q12), until the annotation guide defines it."""

    VERB_NOUN = "verb-noun", _("collocation verbe–nom")
    ADJECTIVE_NOUN = "adjective-noun", _("collocation adjectif–nom")
    ADVERB_VERB = "adverb-verb", _("collocation adverbe–verbe")
    NOUN_NOUN = "noun-noun", _("collocation nom–nom")
    FIXED = "fixed", _("locution figée")
    FORMULA = "formula", _("formule")
    OPEN_SLOT = "open-slot", _("construction à case vide")
    DISCOURSE = "discourse", _("marqueur de discours")
    CLAUSULA = "clausula", _("clausule")


class UsageMark(models.TextChoices):
    POETIC = "poetic", _("poétique seulement")
    LATE = "late", _("tardif")
    AVOID = "avoid", _("à éviter")


class PartQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_withdrawn=False)


class Unit(ModeratedContent):
    """A phraseological unit: a schema of lemmas and its realizations, senses and attestations."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("brouillon")
        PROPOSED = "proposed", _("proposée")
        VALIDATED = "validated", _("validée")
        CONTESTED = "contested", _("contestée")

    reference_form = models.CharField(
        _("forme de référence"),
        max_length=200,
        help_text=_("La forme sous laquelle on cite l’unité, par exemple : consilium capere."),
    )
    kind = models.CharField(_("type"), max_length=20, choices=Kind.choices, blank=True)
    tags = models.JSONField(_("étiquettes"), default=list, blank=True)
    schema = models.CharField(
        _("schéma"),
        max_length=300,
        blank=True,
        help_text=_(
            "Lemmes et relations syntaxiques, le mot qui régit d’abord : capio -obj-> consilium. "
            "Plusieurs relations se séparent par « ; », des variantes par « | »."
        ),
    )
    construction = models.CharField(
        _("construction"),
        max_length=300,
        blank=True,
        help_text=_("Par exemple : consilium capere + infinitif, ou + ut et le subjonctif."),
    )
    register = models.CharField(
        _("registre"), max_length=20, choices=Work.Register.choices, blank=True
    )
    usage_marks = models.JSONField(_("marques d’usage"), default=list, blank=True)
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT, editable=False
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="units",
        verbose_name=_("créée par"),
    )
    created_at = models.DateTimeField(_("créée le"), default=timezone.now, editable=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("validée par"),
    )
    validated_at = models.DateTimeField(_("validée le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("unité phraséologique")
        verbose_name_plural = _("unités phraséologiques")
        ordering = ["reference_form", "pk"]
        indexes = [
            models.Index(fields=["status", "reference_form"], name="phraseology_unit_status")
        ]

    def __str__(self):
        return self.reference_form

    def get_absolute_url(self):
        return reverse("phraseology:unit", args=[self.pk])

    @property
    def is_draft(self):
        return self.status == self.Status.DRAFT

    @property
    def edges(self):
        return parse_schema(self.schema)

    def usage_mark_labels(self):
        labels = dict(UsageMark.choices)
        return [labels[mark] for mark in self.usage_marks if mark in labels]


class Realization(ModeratedContent):
    """A typical form of a unit, such as *bellum geritur* for *bellum gerere*."""

    class Variation(models.TextChoices):
        BASE = "base", _("forme de base")
        PASSIVE = "passive", _("passif")
        WORD_ORDER = "word-order", _("ordre des mots")
        INSERTION = "insertion", _("insertion")
        LEXICAL = "lexical", _("variante lexicale")
        OTHER = "other", _("autre")

    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="realizations", verbose_name=_("unité")
    )
    form = models.CharField(_("forme type"), max_length=200)
    variation = models.CharField(
        _("nature de la variation"),
        max_length=20,
        choices=Variation.choices,
        default=Variation.BASE,
    )
    note = models.CharField(_("note"), max_length=300, blank=True)
    is_withdrawn = models.BooleanField(_("retirée"), default=False)
    created_at = models.DateTimeField(_("ajoutée le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("réalisation")
        verbose_name_plural = _("réalisations")
        ordering = ["unit", "created_at", "pk"]

    def __str__(self):
        return self.form

    def get_absolute_url(self):
        return f"{self.unit.get_absolute_url()}#realisations"


class Sense(ModeratedContent):
    """One sense of a unit; modern equivalents are attached to each sense (Q14)."""

    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="senses", verbose_name=_("unité")
    )
    definition = models.TextField(_("sens"), max_length=1000)
    register = models.CharField(
        _("registre"), max_length=20, choices=Work.Register.choices, blank=True
    )
    usage_note = models.CharField(_("note d’usage"), max_length=300, blank=True)
    is_withdrawn = models.BooleanField(_("retiré"), default=False)
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("sens")
        verbose_name_plural = _("sens")
        ordering = ["unit", "created_at", "pk"]

    def __str__(self):
        return self.definition

    def get_absolute_url(self):
        return f"{self.unit.get_absolute_url()}#sens-{self.pk}"


class Equivalent(ModeratedContent):
    """A modern expression that renders a sense, such as « prendre une décision »."""

    sense = models.ForeignKey(
        Sense, on_delete=models.PROTECT, related_name="equivalents", verbose_name=_("sens")
    )
    language = models.CharField(_("langue"), max_length=2, choices=Language.choices)
    expression = models.CharField(_("expression"), max_length=200)
    is_withdrawn = models.BooleanField(_("retiré"), default=False)
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("équivalent")
        verbose_name_plural = _("équivalents")
        ordering = ["sense", "language", "created_at", "pk"]

    def __str__(self):
        return self.expression

    @property
    def unit(self):
        return self.sense.unit

    def get_absolute_url(self):
        return self.sense.get_absolute_url()


class UnitRelation(ModeratedContent):
    """A link between two units, read from the first: « A est plus général que B » (Q13)."""

    class Kind(models.TextChoices):
        SYNONYM = "synonym", _("synonyme de")
        VARIANT = "variant", _("variante de")
        ANTONYM = "antonym", _("antonyme de")
        BROADER = "broader", _("plus général que")
        NARROWER = "narrower", _("plus précis que")

    INVERSE = {Kind.BROADER: Kind.NARROWER, Kind.NARROWER: Kind.BROADER}

    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="relations", verbose_name=_("unité")
    )
    target = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="+", verbose_name=_("unité liée")
    )
    kind = models.CharField(_("relation"), max_length=10, choices=Kind.choices)
    is_withdrawn = models.BooleanField(_("retirée"), default=False)
    created_at = models.DateTimeField(_("ajoutée le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("relation entre unités")
        verbose_name_plural = _("relations entre unités")
        ordering = ["unit", "kind", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(unit=F("target")), name="phraseology_relation_two_units"
            ),
            models.UniqueConstraint(
                fields=["unit", "target", "kind"],
                condition=Q(is_withdrawn=False),
                name="phraseology_one_active_relation",
            ),
        ]

    def __str__(self):
        return f"{self.unit} · {self.get_kind_display()} · {self.target}"

    def get_absolute_url(self):
        return f"{self.unit.get_absolute_url()}#relations"

    @property
    def inverse_label(self):
        """The relation read from the linked unit."""
        return self.Kind(self.INVERSE.get(self.kind, self.kind)).label


class UnitReference(ModeratedContent):
    """A place in a grammar or a dictionary about the unit, cited without extract (rule 12)."""

    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="references", verbose_name=_("unité")
    )
    work = models.ForeignKey(
        BibliographicWork, on_delete=models.PROTECT, related_name="+", verbose_name=_("ouvrage")
    )
    locator = models.CharField(
        _("localisation"),
        max_length=100,
        help_text=_("Paragraphe, page ou entrée : « § 426 », « s. v. consilium »."),
    )
    note = models.CharField(_("note"), max_length=300, blank=True)
    is_withdrawn = models.BooleanField(_("retiré"), default=False)
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("renvoi bibliographique")
        verbose_name_plural = _("renvois bibliographiques")
        ordering = ["unit", "created_at", "pk"]

    def __str__(self):
        return f"{self.work.abbreviation} {self.locator}"

    def get_absolute_url(self):
        return f"{self.unit.get_absolute_url()}#renvois"


class Attestation(ModeratedContent):
    """Words of the corpus where a unit occurs, pointed to by their stable identifiers (rule 1).

    Validated attestations are checked by people; automatic ones are found by the machine
    and never shown as validated (rule 4).
    """

    class Level(models.TextChoices):
        VALIDATED = "validated", _("vérifiée par des personnes")
        AUTOMATIC = "automatic", _("repérée automatiquement")

    class Origin(models.TextChoices):
        MANUAL = "manual", _("saisie manuelle")
        CANDIDATE = "candidate", _("candidat")
        QUERY = "query", _("requête")

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("proposée")
        VALIDATED = "validated", _("validée")
        REJECTED = "rejected", _("rejetée")

    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, related_name="attestations", verbose_name=_("unité")
    )
    realization = models.ForeignKey(
        Realization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attestations",
        verbose_name=_("réalisation"),
    )
    sense = models.ForeignKey(
        Sense,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attestations",
        verbose_name=_("sens"),
    )
    passage = models.ForeignKey(
        Passage, on_delete=models.PROTECT, related_name="+", verbose_name=_("passage")
    )
    # Stable word identifiers; their order is their position in the edition.
    tokens = models.ManyToManyField(Token, related_name="+", verbose_name=_("mots couverts"))
    level = models.CharField(
        _("niveau"),
        max_length=10,
        choices=Level.choices,
        default=Level.VALIDATED,
        editable=False,
    )
    origin = models.CharField(
        _("origine"), max_length=10, choices=Origin.choices, default=Origin.MANUAL, editable=False
    )
    status = models.CharField(
        _("statut"),
        max_length=10,
        choices=Status.choices,
        default=Status.PROPOSED,
        editable=False,
    )
    is_example = models.BooleanField(
        _("exemple choisi"), default=False, help_text=_("Montré en tête de la fiche.")
    )
    note = models.CharField(_("note"), max_length=300, blank=True)
    is_withdrawn = models.BooleanField(_("retirée"), default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attestations",
        verbose_name=_("ajoutée par"),
    )
    created_at = models.DateTimeField(_("ajoutée le"), default=timezone.now, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("examinée par"),
    )
    reviewed_at = models.DateTimeField(_("examinée le"), null=True, blank=True, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("attestation")
        verbose_name_plural = _("attestations")
        ordering = ["unit", "-is_example", "created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(level="automatic", status="validated"),
                name="phraseology_automatic_never_validated",
            ),
        ]

    def __str__(self):
        return gettext("%(unit)s, %(citation)s") % {
            "unit": self.unit.reference_form,
            "citation": self.passage.citation,
        }

    def get_absolute_url(self):
        return f"{self.unit.get_absolute_url()}#attestation-{self.pk}"

    @property
    def status_label(self):
        """What the attestation is, as shown: an automatic one is never called validated."""
        if self.level == self.Level.AUTOMATIC:
            return self.Level.AUTOMATIC.label
        return self.get_status_display()


class UnitFrequency(models.Model):
    """Occurrences of the schema of a unit found automatically in the corpus: computed, not edited.

    ``by_author`` lists [author id, occurrences, occurrences in the core], chronologically.
    """

    unit = models.OneToOneField(
        Unit, on_delete=models.CASCADE, related_name="frequency", verbose_name=_("unité")
    )
    schema = models.CharField(_("schéma"), max_length=300)
    total = models.PositiveIntegerField(_("occurrences"))
    core_total = models.PositiveIntegerField(_("occurrences dans le noyau"))
    by_author = models.JSONField(_("répartition par auteur"), default=list)
    corpus_version = models.CharField(_("version du corpus"), max_length=200)
    computed_at = models.DateTimeField(_("calculée le"))

    class Meta:
        verbose_name = _("fréquence")
        verbose_name_plural = _("fréquences")

    def __str__(self):
        return f"{self.unit} · {self.total}"


class UnitSurvey(models.Model):
    """The last survey of a unit: its schema's occurrences in the corpus, recorded as automatic
    attestations; those of the core are to be reviewed. Computed, not edited."""

    unit = models.OneToOneField(
        Unit, on_delete=models.CASCADE, related_name="survey", verbose_name=_("unité")
    )
    schema = models.CharField(_("schéma"), max_length=300)
    corpus_version = models.CharField(_("version du corpus"), max_length=200)
    found = models.PositiveIntegerField(_("occurrences repérées"))
    core_found = models.PositiveIntegerField(_("dont dans le noyau"), default=0)
    added = models.PositiveIntegerField(_("attestations ajoutées"))
    remaining = models.PositiveIntegerField(_("occurrences restant à relever"))
    surveyed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("relevé par"),
    )
    surveyed_at = models.DateTimeField(_("relevé le"))

    class Meta:
        verbose_name = _("relevé")
        verbose_name_plural = _("relevés")

    def __str__(self):
        return f"{self.unit} · {self.found}"


class Neologism(ModeratedContent):
    """A Latin word or phrase for a modern reality, justified like any translation choice (T5).

    The Lexicon recentis Latinitatis is cited by reference only, never copied (rule 12).
    """

    class Formation(models.TextChoices):
        PERIPHRASIS = "periphrasis", _("périphrase")
        DERIVATION = "derivation", _("dérivation")
        BORROWING = "borrowing", _("emprunt")

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("proposé")
        VALIDATED = "validated", _("validé")

    form = models.CharField(_("forme latine"), max_length=200)
    meaning = models.TextField(
        _("sens moderne"),
        max_length=1000,
        help_text=_("La réalité moderne que le mot désigne, par exemple : la bicyclette."),
    )
    formation = models.CharField(_("formation"), max_length=20, choices=Formation.choices)
    justification = models.TextField(
        _("justification"),
        max_length=3000,
        help_text=_(
            "Pourquoi ce choix : modèles anciens, analogies, usage des latinistes modernes. "
            "Les preuves du corpus et des ouvrages s’ajoutent ci-dessous."
        ),
    )
    lrl_reference = models.CharField(
        _("Lexicon recentis Latinitatis"),
        max_length=100,
        blank=True,
        help_text=_("Facultatif : l’entrée ou la page, citée sans extrait (« s. v. birota »)."),
    )
    status = models.CharField(
        _("statut"),
        max_length=10,
        choices=Status.choices,
        default=Status.PROPOSED,
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="neologisms",
        verbose_name=_("proposé par"),
    )
    created_at = models.DateTimeField(_("proposé le"), default=timezone.now, editable=False)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name=_("validé par"),
    )
    validated_at = models.DateTimeField(_("validé le"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("néologisme")
        verbose_name_plural = _("néologismes")
        ordering = ["form", "pk"]

    def __str__(self):
        return self.form

    def get_absolute_url(self):
        return reverse("phraseology:neologism", args=[self.pk])


class NeologismEquivalent(ModeratedContent):
    """A modern word rendered by a neologism, such as « vélo » for *birota*."""

    neologism = models.ForeignKey(
        Neologism,
        on_delete=models.PROTECT,
        related_name="equivalents",
        verbose_name=_("néologisme"),
    )
    language = models.CharField(_("langue"), max_length=2, choices=Language.choices)
    expression = models.CharField(_("expression"), max_length=200)
    is_withdrawn = models.BooleanField(_("retiré"), default=False)
    created_at = models.DateTimeField(_("ajouté le"), default=timezone.now, editable=False)

    objects = PartQuerySet.as_manager()

    class Meta:
        verbose_name = _("équivalent d’un néologisme")
        verbose_name_plural = _("équivalents des néologismes")
        ordering = ["neologism", "language", "created_at", "pk"]

    def __str__(self):
        return self.expression

    def get_absolute_url(self):
        return f"{self.neologism.get_absolute_url()}#equivalents"


class NegativeSearch(ModeratedContent):
    """A search that found nothing, recorded with the version of the corpus searched.

    It grounds the mention « introuvable dans le corpus (version X) », never « non attesté »
    (Q18, rule 7).
    """

    expression = models.CharField(
        _("expression cherchée"),
        max_length=200,
        help_text=_("Ce que la recherche devait trouver, par exemple : consilium sumere."),
    )
    query = models.CharField(_("requête"), max_length=2000, editable=False)
    corpus_version = models.CharField(_("version du corpus"), max_length=200, editable=False)
    note = models.TextField(_("note"), max_length=1000, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="negative_searches",
        verbose_name=_("enregistrée par"),
    )
    created_at = models.DateTimeField(_("enregistrée le"), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("recherche infructueuse")
        verbose_name_plural = _("recherches infructueuses")
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.expression

    def get_absolute_url(self):
        return reverse("phraseology:negative_search", args=[self.pk])

    @property
    def search_url(self):
        return f"{reverse('corpus:search')}?{self.query}"


class Candidate(models.Model):
    """Two lemmas linked by a syntactic relation, found by the machine as a possible unit (Q16).

    A candidate is no contribution: the extraction creates and updates it; people retain it,
    by making a unit of it, or reject it, and the decision records who took it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("à examiner")
        RETAINED = "retained", _("retenu")
        REJECTED = "rejected", _("rejeté")

    RELATION_LABELS = {
        "obj": _("objet"),
        "obl": _("complément du verbe"),
        "amod": _("adjectif épithète"),
        "advmod": _("adverbe"),
        "nmod": _("complément du nom"),
        "nsubj": _("sujet"),
    }
    # The relation written in the schema of a unit made from the candidate.
    SCHEMA_RELATIONS = {"obj": "obj|nsubj:pass"}

    head = models.CharField(_("lemme qui régit"), max_length=200)
    relation = models.CharField(_("relation"), max_length=30)
    dependent = models.CharField(_("lemme dépendant"), max_length=200)
    frequency = models.PositiveIntegerField(_("fréquence"))
    score = models.FloatField(_("score d’association"))
    layer = models.ForeignKey(
        AnalysisLayer,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("couche d’analyse"),
    )
    corpus_version = models.CharField(_("version du corpus"), max_length=200)
    extracted_at = models.DateTimeField(_("extrait le"))
    status = models.CharField(
        _("statut"), max_length=10, choices=Status.choices, default=Status.PENDING
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidates",
        verbose_name=_("unité"),
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("décidé par"),
    )
    decided_at = models.DateTimeField(_("décidé le"), null=True, blank=True)

    class Meta:
        verbose_name = _("candidat")
        verbose_name_plural = _("candidats")
        ordering = ["-score", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["head", "relation", "dependent"], name="phraseology_one_candidate_per_pair"
            ),
        ]
        indexes = [models.Index(fields=["status", "-score"], name="phraseology_candidate_queue")]

    def __str__(self):
        return self.label

    def get_absolute_url(self):
        return reverse("phraseology:candidate", args=[self.pk])

    @property
    def label(self):
        return f"{self.head} —{self.relation}→ {self.dependent}"

    @property
    def relation_label(self):
        return self.RELATION_LABELS.get(self.relation, self.relation)

    @property
    def schema(self):
        relation = self.SCHEMA_RELATIONS.get(self.relation, self.relation)
        return f"{self.head} -{relation}-> {self.dependent}"


class UnitForm(models.Model):
    """A normalized word form that recognizes a unit in a sentence: computed, never edited.

    ``lemma`` is a lemma of the schema, or "=word" for a word of the reference form of a unit
    without schema.
    """

    unit = models.ForeignKey(
        Unit, on_delete=models.CASCADE, related_name="forms", verbose_name=_("unité")
    )
    lemma = models.CharField(_("lemme"), max_length=201)
    norm = models.CharField(_("forme normalisée"), max_length=200)

    class Meta:
        verbose_name = _("forme d’une unité")
        verbose_name_plural = _("formes des unités")
        constraints = [
            models.UniqueConstraint(fields=["unit", "lemma", "norm"], name="phraseology_unit_form"),
        ]
        indexes = [models.Index(fields=["norm"], name="phraseology_unit_form_norm")]

    def __str__(self):
        return f"{self.unit} · {self.norm}"


def unit_visible_to(user, unit):
    """A draft is visible to its creator only (rule 8)."""
    return not unit.is_draft or (user.is_authenticated and user.pk == unit.created_by_id)


def part_visible_to(user, part):
    return can_view(user, part.unit)


def unit_owner_id(part):
    return part.unit.created_by_id


register(
    Unit,
    owner_field="created_by",
    text_fields=("reference_form", "schema", "construction"),
    visible_to=unit_visible_to,
    not_reverted=("status", "validated_by", "validated_at"),
    discussion=lambda user, unit: not unit.is_draft,
)
for model, text_fields in (
    (Realization, ("form", "note")),
    (Sense, ("definition", "usage_note")),
    (Equivalent, ("expression",)),
    (UnitRelation, ()),
    (UnitReference, ("locator", "note")),
):
    register(
        model,
        owner_field=unit_owner_id,
        text_fields=text_fields,
        visible_to=part_visible_to,
        counts_toward_limit=False,
    )
register(
    Attestation,
    owner_field="created_by",
    text_fields=("note",),
    visible_to=part_visible_to,
    counts_toward_limit=False,
    not_reverted=("status", "reviewed_by", "reviewed_at", "level", "origin"),
)
register(
    Neologism,
    owner_field="created_by",
    text_fields=("form", "meaning", "justification", "lrl_reference"),
    not_reverted=("status", "validated_by", "validated_at"),
    discussion=lambda user, neologism: True,
)
register(
    NegativeSearch,
    owner_field="created_by",
    text_fields=("expression", "note"),
    not_reverted=("query", "corpus_version"),
)
register(
    NeologismEquivalent,
    owner_field=lambda equivalent: equivalent.neologism.created_by_id,
    text_fields=("expression",),
    visible_to=lambda user, equivalent: can_view(user, equivalent.neologism),
    counts_toward_limit=False,
)
