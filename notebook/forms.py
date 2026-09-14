from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Highlight, PassageList


class HighlightForm(forms.Form):
    color = forms.ChoiceField(
        label=_("Couleur"),
        choices=Highlight.Color.choices,
        initial=Highlight.Color.YELLOW,
        widget=forms.RadioSelect,
    )


class NoteForm(forms.Form):
    text = forms.CharField(
        label=_("Note privée"),
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Vous seul la voyez."),
    )


class ListForm(forms.Form):
    """A list of the reader to add a passage to, or the name of a new one."""

    existing = forms.ModelChoiceField(
        label=_("Liste"), queryset=PassageList.objects.none(), required=False
    )
    name = forms.CharField(label=_("Ou une nouvelle liste"), max_length=100, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["existing"].queryset = PassageList.objects.filter(owner=user)

    def clean(self):
        data = super().clean()
        existing, name = data.get("existing"), " ".join(data.get("name", "").split())
        if not existing and not name:
            raise ValidationError(_("Choisissez une liste ou nommez-en une nouvelle."))
        data["list_name"] = name or existing.name
        return data
