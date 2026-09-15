from urllib.parse import urlencode

from django import forms
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from .models import AnalysisCorrection, Author, Period, Token, Work
from .search import default_layer, parse_term, search_tokens
from .text import normalize

SCOPE_CORE = "core"
SCOPE_ALL = "all"
MODE_FORM = "form"
MODE_LEMMA = "lemma"
TERM_NUMBERS = (1, 2, 3, 4, 5)
# Units looked for by their schema in one search (phraseology.search_terms).
MAX_CONSTRUCTIONS = 3


class CorrectionForm(forms.ModelForm):
    """What a reader changes in the analysis of a word; an empty field stays as it is."""

    head = forms.ModelChoiceField(
        label=_("Dépend du mot"),
        queryset=Token.objects.none(),
        required=False,
        help_text=_("Un mot du même passage ; laissez vide pour ne rien changer."),
    )

    class Meta:
        model = AnalysisCorrection
        fields = ("lemma", "upos", "feats", "deprel", "head", "reason")
        help_texts = {
            "upos": _("Étiquette Universal Dependencies : NOUN, VERB, ADJ, ADV…"),
            "feats": _("Traits Universal Dependencies : Case=Acc|Number=Sing…"),
            "deprel": _("Relation Universal Dependencies : obj, nsubj, obl, amod…"),
        }
        widgets = {
            "lemma": forms.TextInput(attrs={"lang": "la"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, token, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["head"].queryset = token.passage.tokens.exclude(pk=token.pk).order_by(
            "position"
        )
        self.fields["head"].label_from_instance = lambda word: word.form


class WorkChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.citation_prefix} – {obj.title}"


def mode_field():
    return forms.ChoiceField(
        label=_("Chercher comme"),
        choices=[(MODE_FORM, _("forme")), (MODE_LEMMA, _("lemme"))],
        widget=forms.RadioSelect,
        required=False,
    )


class SearchForm(forms.Form):
    """Words of the corpus near each other, and constructions found by the schema of a unit."""

    construction = forms.TypedMultipleChoiceField(
        label=_("Constructions cherchées"),
        help_text=_(
            "Chaque construction se cherche par son schéma, là où l’analyse du corpus la repère ; "
            "décochez-la pour la retirer."
        ),
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    construction_name = forms.CharField(
        label=_("Ajouter une construction"),
        help_text=_("Le nom d’une fiche, par exemple : rēs pūblica."),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"lang": "la"}),
    )
    term1 = forms.CharField(
        label=_("Mot"),
        max_length=100,
        required=False,
        help_text=_("Un mot par case ; * pour un début de mot, | pour des variantes : cap* | cep*"),
    )
    mode1 = mode_field()
    term2 = forms.CharField(label=_("Deuxième mot"), max_length=100, required=False)
    mode2 = mode_field()
    term3 = forms.CharField(label=_("Troisième mot"), max_length=100, required=False)
    mode3 = mode_field()
    term4 = forms.CharField(label=_("Quatrième mot"), max_length=100, required=False)
    mode4 = mode_field()
    term5 = forms.CharField(label=_("Cinquième mot"), max_length=100, required=False)
    mode5 = mode_field()
    distance = forms.IntegerField(
        label=_("Distance maximale (en mots)"),
        help_text=_("Entre le premier mot et chacun des autres."),
        min_value=1,
        max_value=20,
        required=False,
    )
    ordered = forms.BooleanField(label=_("Les mots dans cet ordre"), required=False)
    scope = forms.ChoiceField(
        label=_("Corpus"),
        choices=[(SCOPE_CORE, _("noyau")), (SCOPE_ALL, _("tout le corpus"))],
        widget=forms.RadioSelect,
        required=False,
    )
    authors = forms.ModelMultipleChoiceField(
        label=_("Auteurs"),
        queryset=Author.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    works = WorkChoiceField(
        label=_("Œuvres"),
        queryset=Work.objects.select_related("author"),
        widget=forms.SelectMultiple(attrs={"size": 6}),
        required=False,
    )
    text_forms = forms.MultipleChoiceField(
        label=_("Forme"),
        choices=Work.Form.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    genres = forms.MultipleChoiceField(
        label=_("Genre"),
        choices=Work.Genre.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    registers = forms.MultipleChoiceField(
        label=_("Registre"),
        choices=Work.Register.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    periods = forms.MultipleChoiceField(
        label=_("Époque"),
        choices=Period.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    date_from = forms.IntegerField(
        label=_("Écrit en ou après"),
        help_text=_("Année ; négative avant notre ère."),
        required=False,
    )
    date_to = forms.IntegerField(label=_("Écrit en ou avant"), required=False)

    DEFAULT_DISTANCE = 5

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The units behind constructions are in phraseology, which depends on the corpus.
        from phraseology.search_terms import construction_units

        self.user = user or AnonymousUser()
        # An empty word shows its placeholder: the style sheet hides the empty words after it.
        for number in TERM_NUMBERS:
            self.fields[f"term{number}"].widget.attrs["placeholder"] = " "
        if not self.is_bound:
            values = self.initial.get("construction") or []
        elif hasattr(self.data, "getlist"):
            values = self.data.getlist("construction")
        else:
            values = self.data.get("construction") or []
        pks = [int(value) for value in values if str(value).isdigit()]
        self._show_constructions(construction_units(self.user, pks))

    def _show_constructions(self, units, added=False):
        """The constructions the form offers and shows ticked; a construction added by its name
        joins them and its field is emptied."""
        self.construction_units = units
        self.fields["construction"].choices = [(unit.pk, unit.reference_form) for unit in units]
        if self.is_bound and hasattr(self.data, "setlist"):
            self.data = self.data.copy()
            self.data.setlist("construction", [str(unit.pk) for unit in units])
            if added:
                self.data["construction_name"] = ""

    def _clean_constructions(self, data):
        from phraseology.search_terms import construction_named

        ticked = set(data.get("construction") or [])
        units = [unit for unit in self.construction_units if unit.pk in ticked]
        name = (data.get("construction_name") or "").strip()
        added = False
        if name:
            unit = construction_named(self.user, name)
            if unit is None:
                self.add_error(
                    "construction_name",
                    ValidationError(
                        _("Aucune fiche avec un schéma ne porte ce nom."), code="unknown"
                    ),
                )
            else:
                added = True
                if unit not in units:
                    units.append(unit)
        if len(units) > MAX_CONSTRUCTIONS:
            self.add_error(
                "construction",
                ValidationError(
                    _("Une recherche compte au plus %(limit)d constructions.")
                    % {"limit": MAX_CONSTRUCTIONS},
                    code="too_many",
                ),
            )
            units = units[:MAX_CONSTRUCTIONS]
        self._show_constructions(units, added)
        return units

    def _clean_term(self, name):
        value = self.cleaned_data.get(name, "")
        patterns = parse_term(value).patterns
        if value.strip() and not patterns:
            raise ValidationError(_("Écrivez un mot."), code="empty")
        for pattern in patterns:
            if " " in pattern:
                raise ValidationError(
                    _("Un seul mot par case : utilisez les cases suivantes pour les autres."),
                    code="several_words",
                )
            if pattern.endswith("*") and len(normalize(pattern.rstrip("*"))) < 2:
                raise ValidationError(_("Écrivez au moins deux lettres avant *."), code="short")
        return value

    def clean_term1(self):
        return self._clean_term("term1")

    def clean_term2(self):
        return self._clean_term("term2")

    def clean_term3(self):
        return self._clean_term("term3")

    def clean_term4(self):
        return self._clean_term("term4")

    def clean_term5(self):
        return self._clean_term("term5")

    def term_fields(self):
        """(term, mode) bound fields, in order, for templates."""
        return [(self[f"term{number}"], self[f"mode{number}"]) for number in TERM_NUMBERS]

    @property
    def options_used(self):
        """Whether the distance or the order was changed: their fold then stays open."""
        if not self.is_bound:
            return False
        distance = self.data.get("distance", "").strip()
        return "ordered" in self.data or distance not in ("", str(self.DEFAULT_DISTANCE))

    def clean(self):
        data = super().clean()
        data["construction"] = self._clean_constructions(data)
        words = any(data.get(f"term{number}") for number in TERM_NUMBERS)
        if not words and not data["construction"] and "term1" not in self.errors:
            self.add_error(
                "term1",
                ValidationError(_("Indiquez un mot ou une construction."), code="required"),
            )
        lemma_asked = bool(data["construction"]) or any(
            data.get(f"mode{number}") == MODE_LEMMA for number in TERM_NUMBERS
        )
        if lemma_asked and default_layer() is None:
            raise ValidationError(
                _(
                    "La recherche par lemme n’est pas encore disponible : "
                    "le corpus n’a pas été analysé."
                ),
                code="no_layer",
            )
        return data

    @property
    def terms(self):
        """The constructions first, then the words."""
        from phraseology.search_terms import construction_term

        data = self.cleaned_data
        constructions = [construction_term(unit) for unit in data.get("construction") or []]
        return [term for term in constructions if term] + [
            parse_term(data[f"term{number}"], lemma=data.get(f"mode{number}") == MODE_LEMMA)
            for number in TERM_NUMBERS
            if data.get(f"term{number}")
        ]

    @property
    def search_distance(self):
        return self.cleaned_data.get("distance") or self.DEFAULT_DISTANCE

    @property
    def core_only(self):
        return self.cleaned_data.get("scope") != SCOPE_ALL

    def filters(self):
        data = self.cleaned_data
        keys = ("authors", "works", "text_forms", "genres", "registers", "periods")
        return {
            "core_only": self.core_only,
            **{key: data.get(key) for key in keys},
            "date_from": data.get("date_from"),
            "date_to": data.get("date_to"),
        }

    def hits(self, layer=None):
        """The words found by the valid search."""
        ordered = self.cleaned_data["ordered"]
        return search_tokens(self.terms, self.search_distance, ordered, self.filters(), layer)

    @property
    def filtered(self):
        keys = ("authors", "works", "text_forms", "genres", "registers", "periods")
        data = self.cleaned_data
        dates = (data.get("date_from"), data.get("date_to"))
        return any(data.get(key) for key in keys) or any(date is not None for date in dates)

    def _mode_label(self, number):
        lemma = self.cleaned_data.get(f"mode{number}") == MODE_LEMMA
        return gettext("lemme") if lemma else gettext("forme")

    @property
    def description(self):
        """The valid search in words: its terms, their distance, the part of the corpus."""
        data = self.cleaned_data
        terms = [
            f"{unit.reference_form} ({gettext('construction')})"
            for unit in data.get("construction") or []
        ] + [
            f"{data[f'term{number}']} ({self._mode_label(number)})"
            for number in TERM_NUMBERS
            if data.get(f"term{number}")
        ]
        parts = [" + ".join(terms)]
        if len(terms) > 1:
            distance = self.search_distance
            parts.append(
                ngettext("à %(count)d mot au plus", "à %(count)d mots au plus", distance)
                % {"count": distance}
            )
            if data["ordered"]:
                parts.append(gettext("dans cet ordre"))
        parts.append(gettext("noyau") if self.core_only else gettext("tout le corpus"))
        if self.filtered:
            parts.append(gettext("avec filtres"))
        return ", ".join(parts)


# The parameters of a search, in the order they are written in a stored query.
SEARCH_FIELDS = (
    "construction",
    "term1",
    "mode1",
    "term2",
    "mode2",
    "term3",
    "mode3",
    "term4",
    "mode4",
    "term5",
    "mode5",
    "distance",
    "ordered",
    "scope",
    "authors",
    "works",
    "text_forms",
    "genres",
    "registers",
    "periods",
    "date_from",
    "date_to",
)


def bound_search_form(data, user=None):
    """A search form bound to query parameters (a QueryDict), defaults filling the gaps.

    The constructions are those ``user`` may see; without a user, public units only.
    """
    data = data.copy()
    defaults = {
        "scope": SCOPE_CORE,
        "distance": SearchForm.DEFAULT_DISTANCE,
        **{f"mode{number}": MODE_FORM for number in TERM_NUMBERS},
    }
    for key, value in defaults.items():
        data.setdefault(key, str(value))
    return SearchForm(data, user=user)


def search_query(data):
    """The search parameters of a QueryDict as a query string, nothing else and in order."""
    return urlencode(
        [(key, value) for key in SEARCH_FIELDS for value in data.getlist(key) if value]
    )
