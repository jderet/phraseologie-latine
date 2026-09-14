from django import forms

from .models import GuideVersion


class GuideForm(forms.ModelForm):
    class Meta:
        model = GuideVersion
        fields = ("text", "summary")
        widgets = {"text": forms.Textarea(attrs={"rows": 30})}
