from urllib.parse import urlencode

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from .models import Author, Period, Work
from .search import default_layer, parse_term, search_tokens
from .text import normalize

SCOPE_CORE = "core"
SCOPE_ALL = "all"
MODE_FORM = "form"
MODE_LEMMA = "lemma"
TERM_NUMBERS = (1, 2, 3)


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
    term1 = forms.CharField(
        label=_("Mot"),
        max_length=100,
        help_text=_("Un mot par case ; * pour un début de mot, | pour des variantes : cap* | cep*"),
    )
    mode1 = mode_field()
    term2 = forms.CharField(label=_("Deuxième mot"), max_length=100, required=False)
    mode2 = mode_field()
    term3 = forms.CharField(label=_("Troisième mot"), max_length=100, required=False)
    mode3 = mode_field()
    distance = forms.IntegerField(
        label=_("Distance maximale (en mots)"), min_value=1, max_value=20, required=False
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

    def clean(self):
        data = super().clean()
        lemma_asked = any(data.get(f"mode{number}") == MODE_LEMMA for number in TERM_NUMBERS)
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
        data = self.cleaned_data
        return [
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
    "term1",
    "mode1",
    "term2",
    "mode2",
    "term3",
    "mode3",
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


def bound_search_form(data):
    """A search form bound to query parameters (a QueryDict), defaults filling the gaps."""
    data = data.copy()
    defaults = {
        "scope": SCOPE_CORE,
        "distance": SearchForm.DEFAULT_DISTANCE,
        **{f"mode{number}": MODE_FORM for number in TERM_NUMBERS},
    }
    for key, value in defaults.items():
        data.setdefault(key, str(value))
    return SearchForm(data)


def search_query(data):
    """The search parameters of a QueryDict as a query string, nothing else and in order."""
    return urlencode(
        [(key, value) for key in SEARCH_FIELDS for value in data.getlist(key) if value]
    )
