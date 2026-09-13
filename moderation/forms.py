from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Report


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ("reason", "message")
        widgets = {
            "reason": forms.RadioSelect,
            "message": forms.Textarea(attrs={"rows": 4}),
        }


class ResolveReportForm(forms.Form):
    HANDLED = "handled"
    HIDE = "hide"
    REJECTED = "rejected"

    decision = forms.ChoiceField(
        label=_("Décision"),
        choices=[
            (HANDLED, _("Traité, contenu laissé en ligne")),
            (HIDE, _("Traité, contenu masqué")),
            (REJECTED, _("Rejeté")),
        ],
        widget=forms.RadioSelect,
    )
    resolution = forms.CharField(
        label=_("Note"),
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
