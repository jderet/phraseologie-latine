from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Author, Period, Work
from .search import parse_term
from .text import normalize

SCOPE_CORE = "core"
SCOPE_ALL = "all"


class WorkChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.citation_prefix} – {obj.title}"


class SearchForm(forms.Form):
    term1 = forms.CharField(
        label=_("Mot"),
        max_length=100,
        help_text=_("Un mot par case ; * pour un début de mot, | pour des variantes : cap* | cep*"),
    )
    term2 = forms.CharField(label=_("Deuxième mot"), max_length=100, required=False)
    term3 = forms.CharField(label=_("Troisième mot"), max_length=100, required=False)
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
        patterns = parse_term(value)
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

    @property
    def terms(self):
        names = ("term1", "term2", "term3")
        return [
            parse_term(self.cleaned_data[name]) for name in names if self.cleaned_data.get(name)
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
