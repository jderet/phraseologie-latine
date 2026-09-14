from django.db import models, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

URN_PREFIX = "urn:cts:latinLit:"


def format_reference(reference):
    """Usual way of writing a reference: 1.23.4 becomes 1, 23, 4."""
    return ", ".join(reference.split("."))


class Period(models.TextChoices):
    ARCHAIC = "archaic", _("latin archaïque")
    CLASSICAL = "classical", _("latin classique")
    IMPERIAL = "imperial", _("latin impérial")
    LATE = "late", _("latin tardif")
    MEDIEVAL = "medieval", _("latin médiéval")
    NEO = "neo", _("néo-latin")


class Author(models.Model):
    cts_id = models.CharField(_("identifiant CTS"), max_length=20, unique=True)
    name_fr = models.CharField(_("nom en français"), max_length=100)
    name_en = models.CharField(_("nom en anglais"), max_length=100)
    latin_name = models.CharField(_("nom latin"), max_length=100)
    abbreviation = models.CharField(_("abréviation"), max_length=20)
    birth_year = models.IntegerField(_("année de naissance"), null=True, blank=True)
    death_year = models.IntegerField(_("année de mort"), null=True, blank=True)
    period = models.CharField(_("époque"), max_length=20, choices=Period.choices, blank=True)

    class Meta:
        verbose_name = _("auteur")
        verbose_name_plural = _("auteurs")
        ordering = ["birth_year", "cts_id"]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return self.name_en if (get_language() or "").startswith("en") else self.name_fr


class Work(models.Model):
    class Genre(models.TextChoices):
        ORATORY = "oratory", _("éloquence")
        RHETORIC = "rhetoric", _("rhétorique")
        PHILOSOPHY = "philosophy", _("philosophie")
        LETTERS = "letters", _("lettres")
        HISTORY = "history", _("histoire")
        BIOGRAPHY = "biography", _("biographie")
        TECHNICAL = "technical", _("traité technique")
        MISCELLANY = "miscellany", _("miscellanées")
        NOVEL = "novel", _("roman")
        TRAGEDY = "tragedy", _("tragédie")
        COMEDY = "comedy", _("comédie")
        EPIC = "epic", _("épopée")
        DIDACTIC = "didactic", _("poésie didactique")
        BUCOLIC = "bucolic", _("bucolique")
        LYRIC = "lyric", _("poésie lyrique")
        ELEGY = "elegy", _("élégie")
        EPIGRAM = "epigram", _("épigramme")
        FABLE = "fable", _("fable")
        SATIRE = "satire", _("satire")

    class Register(models.TextChoices):
        ELEVATED = "elevated", _("soutenu")
        STANDARD = "standard", _("courant")
        FAMILIAR = "familiar", _("familier")

    class Form(models.TextChoices):
        PROSE = "prose", _("prose")
        VERSE = "verse", _("vers")
        PROSIMETRUM = "prosimetrum", _("prosimètre")

    author = models.ForeignKey(
        Author, on_delete=models.PROTECT, related_name="works", verbose_name=_("auteur")
    )
    cts_urn = models.CharField(_("URN CTS"), max_length=100, unique=True)
    title = models.CharField(_("titre"), max_length=200)
    abbreviation = models.CharField(_("abréviation"), max_length=30, blank=True)
    genre = models.CharField(_("genre"), max_length=20, choices=Genre.choices, blank=True)
    register = models.CharField(_("registre"), max_length=20, choices=Register.choices, blank=True)
    form = models.CharField(_("forme"), max_length=20, choices=Form.choices, default=Form.PROSE)
    date_from = models.IntegerField(_("date de début"), null=True, blank=True)
    date_to = models.IntegerField(_("date de fin"), null=True, blank=True)
    is_core = models.BooleanField(
        _("noyau"),
        default=False,
        help_text=_("Les attestations du noyau sont vérifiées par des personnes."),
    )
    is_fragmentary = models.BooleanField(_("fragmentaire"), default=False)

    class Meta:
        verbose_name = _("œuvre")
        verbose_name_plural = _("œuvres")
        ordering = ["author__birth_year", "cts_urn"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("corpus:work", args=[self.cts_id])

    @property
    def cts_id(self):
        return self.cts_urn.removeprefix(URN_PREFIX)

    @property
    def citation_prefix(self):
        """Author and work abbreviations, as in Cic. Off."""
        return " ".join(part for part in (self.author.abbreviation, self.abbreviation) if part)


class Edition(models.Model):
    """An imported edition. It never changes: importing a new version creates a new edition."""

    work = models.ForeignKey(
        Work, on_delete=models.PROTECT, related_name="editions", verbose_name=_("œuvre")
    )
    cts_urn = models.CharField(_("URN CTS"), max_length=120)
    source = models.CharField(_("source"), max_length=100)
    source_path = models.CharField(_("fichier"), max_length=255)
    source_version = models.CharField(
        _("version de la source"), max_length=40, help_text=_("Commit Git du dépôt importé.")
    )
    license = models.CharField(_("licence"), max_length=50)
    citation_scheme = models.JSONField(_("schéma de citation"), default=list, blank=True)
    imported_at = models.DateTimeField(_("importée le"), default=timezone.now)
    is_current = models.BooleanField(_("édition en usage"), default=True)
    passage_count = models.PositiveIntegerField(_("nombre de passages"), default=0)
    token_count = models.PositiveIntegerField(_("nombre de mots"), default=0)

    class Meta:
        verbose_name = _("édition")
        verbose_name_plural = _("éditions")
        ordering = ["work", "-imported_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cts_urn", "source_version"], name="corpus_edition_version"
            ),
            models.UniqueConstraint(
                fields=["work"], condition=Q(is_current=True), name="corpus_one_current_edition"
            ),
        ]

    def __str__(self):
        return f"{self.cts_urn} ({self.source_version[:7]})"


class Passage(models.Model):
    """The smallest citable unit of an edition (section, letter section, line)."""

    edition = models.ForeignKey(
        Edition, on_delete=models.CASCADE, related_name="passages", verbose_name=_("édition")
    )
    order = models.PositiveIntegerField(_("ordre"))
    reference = models.CharField(_("référence"), max_length=50)
    heading = models.CharField(_("titre"), max_length=300, blank=True)
    text = models.TextField(_("texte"))

    class Meta:
        verbose_name = _("passage")
        verbose_name_plural = _("passages")
        ordering = ["edition", "order"]
        constraints = [
            models.UniqueConstraint(fields=["edition", "order"], name="corpus_passage_order"),
            models.UniqueConstraint(
                fields=["edition", "reference"], name="corpus_passage_reference"
            ),
        ]

    def __str__(self):
        return self.citation

    def get_absolute_url(self):
        return reverse("corpus:passage", args=[self.edition.work.cts_id, self.reference])

    @property
    def urn(self):
        return f"{self.edition.cts_urn}:{self.reference}"

    @property
    def citation(self):
        return f"{self.edition.work.citation_prefix} {format_reference(self.reference)}"


class Token(models.Model):
    """A word of an edition.

    Its identifier never changes for a given edition, so human annotations can point to it;
    (edition, position) is the readable equivalent used in exports.
    """

    edition = models.ForeignKey(
        Edition, on_delete=models.CASCADE, related_name="tokens", verbose_name=_("édition")
    )
    passage = models.ForeignKey(
        Passage, on_delete=models.CASCADE, related_name="tokens", verbose_name=_("passage")
    )
    position = models.PositiveIntegerField(_("position dans l’édition"))
    form = models.CharField(_("forme imprimée"), max_length=200)
    norm = models.CharField(_("forme normalisée"), max_length=200)
    before = models.CharField(_("ponctuation avant"), max_length=50, blank=True)
    after = models.CharField(_("ponctuation et espace après"), max_length=200, blank=True)
    is_foreign = models.BooleanField(_("mot étranger"), default=False)

    class Meta:
        verbose_name = _("mot")
        verbose_name_plural = _("mots")
        ordering = ["edition", "position"]
        constraints = [
            models.UniqueConstraint(fields=["edition", "position"], name="corpus_token_position"),
        ]
        indexes = [
            # varchar_pattern_ops also serves prefix searches (consili*).
            models.Index(
                fields=["norm"], name="corpus_token_norm", opclasses=["varchar_pattern_ops"]
            ),
        ]

    def __str__(self):
        return self.form


class AnalysisLayer(models.Model):
    """One run of an analysis tool over the corpus; running a tool again creates a new layer."""

    tool = models.CharField(_("outil"), max_length=100)
    tool_version = models.CharField(_("version de l’outil"), max_length=50, blank=True)
    details = models.JSONField(_("détails"), default=dict, blank=True)
    created_at = models.DateTimeField(_("créée le"), default=timezone.now)
    editions = models.ManyToManyField(
        Edition, related_name="analysis_layers", blank=True, verbose_name=_("éditions analysées")
    )
    is_default = models.BooleanField(
        _("couche par défaut"),
        default=False,
        help_text=_("Couche utilisée par la recherche par lemme."),
    )

    class Meta:
        verbose_name = _("couche d’analyse")
        verbose_name_plural = _("couches d’analyse")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="corpus_one_default_layer"
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        return f"{self.tool} {self.tool_version}".strip()

    @transaction.atomic
    def make_default(self):
        AnalysisLayer.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        self.is_default = True
        self.save(update_fields=["is_default"])


class TokenAnalysis(models.Model):
    """Analysis of a word, or of one part of it such as an enclitic, in a layer."""

    class Origin(models.TextChoices):
        VERIFIED = "verified", _("import vérifié")
        AUTOMATIC = "automatic", _("automatique")
        CORRECTED = "corrected", _("correction humaine")

    layer = models.ForeignKey(
        AnalysisLayer, on_delete=models.CASCADE, related_name="analyses", verbose_name=_("couche")
    )
    token = models.ForeignKey(
        Token, on_delete=models.CASCADE, related_name="analyses", verbose_name=_("mot")
    )
    part = models.PositiveSmallIntegerField(_("partie du mot"), default=0)
    text = models.CharField(_("texte analysé"), max_length=200)
    lemma = models.CharField(_("lemme"), max_length=200, blank=True)
    lemma_norm = models.CharField(_("lemme normalisé"), max_length=200, blank=True)
    upos = models.CharField(_("catégorie"), max_length=10, blank=True)
    feats = models.CharField(_("traits morphologiques"), max_length=300, blank=True)
    head = models.ForeignKey(
        Token,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
        verbose_name=_("tête syntaxique"),
    )
    head_part = models.PositiveSmallIntegerField(_("partie de la tête"), default=0)
    deprel = models.CharField(_("relation syntaxique"), max_length=30, blank=True)
    sentence = models.PositiveIntegerField(_("phrase"), default=0)
    origin = models.CharField(
        _("origine"), max_length=10, choices=Origin.choices, default=Origin.AUTOMATIC
    )

    class Meta:
        verbose_name = _("analyse d’un mot")
        verbose_name_plural = _("analyses des mots")
        ordering = ["layer", "token", "part"]
        constraints = [
            models.UniqueConstraint(fields=["layer", "token", "part"], name="corpus_analysis_part"),
        ]
        indexes = [
            models.Index(
                fields=["layer", "lemma_norm"],
                name="corpus_analysis_lemma",
                opclasses=["int8_ops", "varchar_pattern_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.text} : {self.lemma}"
