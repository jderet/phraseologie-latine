from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from accounts.limits import check_text_for_links
from translations.forms import ContributionForm
from translations.services import normalize_sentence

from .models import BibliographicWork, Justification
from .services import reference_evidence


class JustificationForm(ContributionForm):
    link_fields = ("source_excerpt", "comment")

    class Meta:
        model = Justification
        fields = ("latin_excerpt", "source_excerpt", "strength", "comment")
        widgets = {
            "latin_excerpt": forms.TextInput(attrs={"lang": "la"}),
            "strength": forms.RadioSelect,
            "comment": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, translated, **kwargs):
        self.translated = translated
        super().__init__(*args, **kwargs)

    def clean_latin_excerpt(self):
        excerpt = normalize_sentence(self.cleaned_data["latin_excerpt"])
        if excerpt not in self.translated.text:
            raise ValidationError(
                _("Ce passage ne figure pas dans la phrase latine : copiez-le tel quel."),
                code="excerpt_not_found",
            )
        return excerpt

    def clean_source_excerpt(self):
        excerpt = normalize_sentence(self.cleaned_data["source_excerpt"])
        if excerpt and excerpt not in self.translated.segment.text:
            raise ValidationError(
                _("Ce passage ne figure pas dans la phrase source."), code="source_not_found"
            )
        return excerpt


class ReferenceForm(forms.Form):
    """A place in a grammar or a dictionary; the work is cited, never quoted."""

    work = forms.ModelChoiceField(
        label=_("Ouvrage"), queryset=BibliographicWork.objects.all(), required=False
    )
    locator = forms.CharField(
        label=_("Localisation"),
        max_length=100,
        required=False,
        help_text=_("Paragraphe, page ou entrée : « § 426 », « s. v. consilium »."),
    )
    note = forms.CharField(label=_("Note"), max_length=300, required=False)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("work") and not data.get("locator"):
            self.add_error("locator", _("Indiquez le paragraphe, la page ou l’entrée."))
        if data.get("locator") and not data.get("work"):
            self.add_error("work", _("Choisissez l’ouvrage cité."))
        for name in ("locator", "note"):
            try:
                check_text_for_links(self.user, data.get(name, ""))
            except ValidationError as error:
                self.add_error(name, error)
        return data

    def evidence(self):
        data = self.cleaned_data
        if not data.get("work"):
            return None
        return reference_evidence(data["work"], data["locator"], data["note"])


ReferenceFormSet = forms.formset_factory(ReferenceForm, extra=2, max_num=5)
