import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from accounts.limits import check_text_for_links
from corpus.forms import SCOPE_ALL, SCOPE_CORE
from corpus.models import Work
from translations.forms import ContributionForm
from translations.models import Language
from translations.services import normalize_sentence

from .abstract import (
    FEATURES,
    MAX_RULES,
    PARTS_OF_SPEECH,
    RULE_PARTS_OF_SPEECH,
    clean_name,
    clean_rules,
)
from .markup import MARK, clean_marks, plain_form
from .models import (
    AbstractWord,
    Equivalent,
    NegativeSearch,
    Neologism,
    NeologismEquivalent,
    Realization,
    Sense,
    Unit,
    UnitReference,
    UnitRelation,
    UsageMark,
)
from .schema import format_schema, parse_schema
from .widgets import SchemaWidget

MAX_TAGS = 10
MAX_MARKED_LENGTH = 300


class MarkedReferenceFormMixin:
    """The reference form, where a unit it is made of may be marked: [rēs pūblica;rem pūblicam].

    The unit keeps the plain form as its reference form, and the marked text beside it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reference_form"] = forms.CharField(
            label=_("Forme de référence"),
            max_length=MAX_MARKED_LENGTH,
            help_text=_(
                "La forme sous laquelle on cite l’unité, par exemple : consilium capere. Une "
                "fiche qu’elle contient se marque entre crochets, son nom puis ses mots : "
                "[rēs pūblica;rem pūblicam] administrāre."
            ),
            widget=forms.TextInput(attrs={"lang": "la"}),
        )
        if not self.is_bound and self.instance.marked_form:
            self.initial["reference_form"] = self.instance.marked_form

    def clean_reference_form(self):
        marked = clean_marks(normalize_sentence(self.cleaned_data["reference_form"]))
        plain = normalize_sentence(plain_form(marked))
        limit = Unit._meta.get_field("reference_form").max_length
        if not plain:
            raise ValidationError(_("Indiquez la forme de référence."), code="required")
        if len(plain) > limit:
            raise ValidationError(
                _("La forme de référence compte au plus %(limit)d caractères.") % {"limit": limit},
                code="max_length",
            )
        self.instance.marked_form = marked if MARK.search(marked) else ""
        return plain


MAX_TAG_LENGTH = 40


class UnitCreateForm(MarkedReferenceFormMixin, ContributionForm):
    """The three fields a unit needs to be created; the attestation is chosen in the corpus."""

    link_fields = ("reference_form", "definition")

    definition = forms.CharField(
        label=_("Sens"),
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Une définition courte ; les équivalents modernes s’ajoutent ensuite."),
    )

    class Meta:
        model = Unit
        fields = ("reference_form", "schema")
        widgets = {
            "reference_form": forms.TextInput(attrs={"lang": "la"}),
            "schema": SchemaWidget(
                words_from="reference_form",
                count=True,
                search="attestation-search",
                keep={"reference_form": "forme", "schema": "schema", "definition": "sens"},
            ),
        }

    def clean_schema(self):
        return format_schema(parse_schema(self.cleaned_data["schema"]))


class CandidateUnitForm(UnitCreateForm):
    """A unit made from a candidate, which receives the schema of the candidate."""

    class Meta(UnitCreateForm.Meta):
        fields = ("reference_form",)


class UnitForm(MarkedReferenceFormMixin, ContributionForm):
    link_fields = ("reference_form", "construction")

    usage_marks = forms.MultipleChoiceField(
        label=_("Marques d’usage"),
        choices=UsageMark.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    tags = forms.CharField(
        label=_("Étiquettes"),
        max_length=500,
        required=False,
        help_text=_("Libres, séparées par des virgules : guerre, décision."),
    )

    class Meta:
        model = Unit
        fields = (
            "reference_form",
            "kind",
            "schema",
            "construction",
            "register",
            "usage_marks",
            "tags",
        )
        help_texts = {
            "kind": _("Typologie provisoire, en attendant le guide d’annotation."),
        }
        widgets = {
            "reference_form": forms.TextInput(attrs={"lang": "la"}),
            "schema": SchemaWidget(words_from="reference_form", count=True),
            "construction": forms.TextInput(attrs={"lang": "la"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["tags"] = ", ".join(self.instance.tags)

    def clean_schema(self):
        return format_schema(parse_schema(self.cleaned_data["schema"]))

    def clean_tags(self):
        tags = []
        for tag in self.cleaned_data["tags"].split(","):
            tag = " ".join(tag.split()).lower()
            if tag and tag not in tags:
                tags.append(tag)
        if len(tags) > MAX_TAGS:
            raise ValidationError(
                ngettext("%(limit)d étiquette au plus.", "%(limit)d étiquettes au plus.", MAX_TAGS)
                % {"limit": MAX_TAGS},
                code="too_many_tags",
            )
        if any(len(tag) > MAX_TAG_LENGTH for tag in tags):
            raise ValidationError(
                _("Une étiquette compte au plus %(limit)d caractères.") % {"limit": MAX_TAG_LENGTH},
                code="long_tag",
            )
        check_text_for_links(self.user, *tags)
        return tags


class PartForm(ContributionForm):
    """A form about one part of a unit."""

    def __init__(self, *args, unit, **kwargs):
        self.unit = unit
        super().__init__(*args, **kwargs)


class SenseForm(PartForm):
    link_fields = ("definition", "usage_note")

    class Meta:
        model = Sense
        fields = ("definition", "register", "usage_note")
        widgets = {"definition": forms.Textarea(attrs={"rows": 3})}


class EquivalentForm(PartForm):
    link_fields = ("expression",)

    class Meta:
        model = Equivalent
        fields = ("sense", "language", "expression")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["sense"]
        field.queryset = self.unit.senses.active()
        field.label_from_instance = lambda sense: Truncator(sense.definition).chars(90)
        if field.queryset.count() == 1:
            field.initial = field.queryset.get()

    def clean_expression(self):
        return normalize_sentence(self.cleaned_data["expression"])


class RealizationForm(PartForm):
    link_fields = ("form", "note")

    class Meta:
        model = Realization
        fields = ("form", "variation", "note")
        widgets = {"form": forms.TextInput(attrs={"lang": "la"})}

    def clean_form(self):
        return normalize_sentence(self.cleaned_data["form"])


class RelationForm(PartForm):
    class Meta:
        model = UnitRelation
        fields = ("kind", "target")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["target"]
        field.queryset = (
            Unit.objects.exclude(status=Unit.Status.DRAFT)
            .filter(is_hidden=False)
            .exclude(pk=self.unit.pk)
        )
        field.label_from_instance = lambda unit: unit.reference_form

    def clean(self):
        data = super().clean()
        duplicates = self.unit.relations.active().filter(
            target=data.get("target"), kind=data.get("kind")
        )
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError(_("Cette relation est déjà indiquée."), code="duplicate")
        return data


class UnitReferenceForm(PartForm):
    link_fields = ("locator", "note")

    class Meta:
        model = UnitReference
        fields = ("work", "locator", "note")


class NeologismForm(ContributionForm):
    link_fields = ("form", "meaning", "justification", "lrl_reference")

    class Meta:
        model = Neologism
        fields = ("form", "meaning", "formation", "justification", "lrl_reference")
        widgets = {
            "form": forms.TextInput(attrs={"lang": "la"}),
            "meaning": forms.Textarea(attrs={"rows": 2}),
            "justification": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_form(self):
        return normalize_sentence(self.cleaned_data["form"])


class NeologismCreateForm(NeologismForm):
    link_fields = (*NeologismForm.link_fields, "expression")

    language = forms.ChoiceField(
        label=_("Langue de l’équivalent"), choices=Language.choices, initial=Language.FRENCH
    )
    expression = forms.CharField(
        label=_("Équivalent moderne"),
        max_length=200,
        help_text=_("Le mot courant, par exemple : vélo. D’autres s’ajoutent ensuite."),
    )

    def clean_expression(self):
        return normalize_sentence(self.cleaned_data["expression"])


class AbstractWordForm(ContributionForm):
    """An abstract word and its rules, one group of fields for each rule.

    A word belongs to the class when it meets everything filled in on one line.
    """

    link_fields = ("label", "definition")

    class Meta:
        model = AbstractWord
        fields = ("name", "label", "definition")
        widgets = {"definition": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # The name is written in the units that use the word: it does not change.
            self.fields["name"].disabled = True
            self.fields["name"].help_text = _("Le nom ne change plus : les fiches l’emploient.")
        rules = list(self.instance.rules or [])
        for number in range(1, MAX_RULES + 1):
            rule = rules[number - 1] if number <= len(rules) else {}
            self.fields[f"upos{number}"] = forms.MultipleChoiceField(
                label=_("Catégories"),
                required=False,
                choices=[(code, PARTS_OF_SPEECH[code]) for code in RULE_PARTS_OF_SPEECH],
                widget=forms.CheckboxSelectMultiple(attrs={"class": "abstract-parts"}),
                initial=rule.get("upos", []),
            )
            for feature, (label, choices) in FEATURES.items():
                chosen = [value for value, _label in choices if value in rule.get("feats", [])]
                self.fields[f"{feature.lower()}{number}"] = forms.ChoiceField(
                    label=label,
                    required=False,
                    choices=[("", _("— tous —")), *choices],
                    initial=chosen[0] if chosen else "",
                )
            self.fields[f"lemmas{number}"] = forms.CharField(
                label=_("Lemmes"),
                required=False,
                max_length=1000,
                help_text=_("Séparés par des virgules : aqua, uinum, potio."),
                widget=forms.TextInput(attrs={"lang": "la", "spellcheck": "false"}),
                initial=", ".join(rule.get("lemmas", [])),
            )

    def rule_rows(self):
        """The fields of each rule, for the template: (number, parts of speech, the others)."""
        return [
            (
                number,
                self[f"upos{number}"],
                [self[f"{feature.lower()}{number}"] for feature in FEATURES]
                + [self[f"lemmas{number}"]],
            )
            for number in range(1, MAX_RULES + 1)
        ]

    def clean_name(self):
        if self.instance.pk:
            return self.instance.name
        name = clean_name(self.cleaned_data["name"])
        if AbstractWord.objects.filter(name=name).exists():
            raise ValidationError(
                _("Un mot abstrait porte déjà ce nom."), code="abstract_name_taken"
            )
        return name

    def clean(self):
        data = super().clean()
        rules = []
        for number in range(1, MAX_RULES + 1):
            text = data.get(f"lemmas{number}", "") or ""
            rules.append(
                {
                    "upos": data.get(f"upos{number}") or [],
                    "feats": [
                        data[f"{feature.lower()}{number}"]
                        for feature in FEATURES
                        if data.get(f"{feature.lower()}{number}")
                    ],
                    "lemmas": [lemma for lemma in re.split(r"[,;\s]+", text) if lemma],
                }
            )
        try:
            self.instance.rules = clean_rules(rules)
        except ValidationError as error:
            self.add_error(None, error)
        return data


class NeologismEquivalentForm(ContributionForm):
    link_fields = ("expression",)

    class Meta:
        model = NeologismEquivalent
        fields = ("language", "expression")

    def clean_expression(self):
        return normalize_sentence(self.cleaned_data["expression"])


class ContestForm(forms.Form):
    argument = forms.CharField(
        label=_("Argument"),
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=_("Ce qui vous paraît fautif dans la fiche, et ce que vous proposez."),
    )


class ResolveContestForm(forms.Form):
    status = forms.ChoiceField(
        label=_("Décision"),
        choices=[
            (Unit.Status.VALIDATED, _("Valider la fiche : la contestation est écartée")),
            (Unit.Status.PROPOSED, _("Remettre la fiche en proposition : elle doit être revue")),
        ],
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        label=_("Motivation"), max_length=3000, widget=forms.Textarea(attrs={"rows": 3})
    )


class AttestationPlaceForm(forms.Form):
    """The sense and the realization the chosen attestations illustrate, if known."""

    sense = forms.ModelChoiceField(label=_("Sens"), queryset=Sense.objects.none(), required=False)
    realization = forms.ModelChoiceField(
        label=_("Réalisation"), queryset=Realization.objects.none(), required=False
    )

    def __init__(self, *args, unit, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sense"].queryset = unit.senses.active()
        self.fields["sense"].label_from_instance = lambda sense: Truncator(sense.definition).chars(
            90
        )
        self.fields["realization"].queryset = unit.realizations.active()


class AnnotationForm(AttestationPlaceForm):
    """Words chosen in the text being read, attached to a unit with what the reader adds."""

    unit = forms.IntegerField(widget=forms.HiddenInput)
    words = forms.CharField(max_length=2000, widget=forms.HiddenInput)
    note = forms.CharField(label=_("Note"), max_length=300, required=False)
    example_proposed = forms.BooleanField(
        label=_("Proposer comme exemple de la fiche"),
        required=False,
        help_text=_("Un relecteur décide d’en faire un exemple choisi."),
    )

    def __init__(self, *args, unit, user, **kwargs):
        self.user = user
        super().__init__(*args, unit=unit, **kwargs)

    def clean_note(self):
        note = " ".join(self.cleaned_data["note"].split())
        check_text_for_links(self.user, note)
        return note


class DoubtForm(forms.Form):
    reason = forms.CharField(
        label=_("Motif"),
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Pourquoi ces mots n’attestent pas l’unité, à votre avis."),
    )


class AttestationResolveForm(forms.Form):
    decision = forms.ChoiceField(
        label=_("Décision"),
        choices=[
            ("keep", _("Maintenir l’attestation telle quelle")),
            ("validate", _("Valider l’attestation")),
            ("reject", _("Rejeter l’attestation")),
        ],
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        label=_("Motivation"), max_length=3000, widget=forms.Textarea(attrs={"rows": 3})
    )


class SightingForm(forms.Form):
    note = forms.CharField(
        label=_("Note"),
        max_length=300,
        required=False,
        help_text=_("Facultatif : ce que vous y voyez, par exemple « formule de politesse ? »."),
    )


class ReadingNoteForm(forms.Form):
    text = forms.CharField(
        label=_("Note"),
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Un commentaire public sur ces mots : tournure, allusion, difficulté."),
    )


class NegativeSearchForm(forms.ModelForm):
    """What a person adds to a search that found nothing; the query comes from the search."""

    class Meta:
        model = NegativeSearch
        fields = ("expression", "note")
        widgets = {
            "expression": forms.TextInput(attrs={"lang": "la"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }


class SchemaSearchForm(forms.Form):
    """A query by schema: lemmas linked by syntactic relations, one of them possibly left open."""

    schema = forms.CharField(
        label=_("Schéma"),
        max_length=300,
        help_text=_(
            "Le lemme qui régit d’abord : capio -obj|nsubj:pass-> consilium ; "
            "« ; » entre les relations ; * pour une case vide : capio -obj-> *"
        ),
        widget=SchemaWidget(slot=True),
    )
    scope = forms.ChoiceField(
        label=_("Corpus"),
        choices=[(SCOPE_CORE, _("noyau")), (SCOPE_ALL, _("tout le corpus"))],
        widget=forms.RadioSelect,
        required=False,
    )
    text_forms = forms.MultipleChoiceField(
        label=_("Forme"),
        choices=Work.Form.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def clean_schema(self):
        edges = parse_schema(self.cleaned_data["schema"], slot=True)
        if not edges:
            raise ValidationError(_("Écrivez au moins une relation."), code="empty")
        return edges

    @property
    def core_only(self):
        return self.cleaned_data.get("scope") != SCOPE_ALL
