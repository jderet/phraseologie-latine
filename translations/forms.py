from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from accounts.limits import check_text_for_links

from .models import SourceText, TranslationProject, TranslationVersion, VersionStep
from .segmentation import from_lines
from .services import normalize_sentence

MAX_SENTENCES = 500
MAX_SENTENCE_LENGTH = 2000
MAX_LATIN_LENGTH = 4000


class ContributionForm(forms.ModelForm):
    """A form whose free-text fields may not contain links when the author is a new account."""

    link_fields = ()

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        for name in self.link_fields:
            try:
                check_text_for_links(self.user, data.get(name, ""))
            except ValidationError as error:
                self.add_error(name, error)
        return data


class SourceTextEditForm(ContributionForm):
    link_fields = ("title", "author")

    class Meta:
        model = SourceText
        fields = ("title", "author", "author_death_year", "language", "source_url", "license")


class SourceTextForm(SourceTextEditForm):
    link_fields = ("title", "author", "text")

    declaration = forms.BooleanField(
        label=_(
            "Je déclare que ce texte est dans le domaine public ou publié sous la licence indiquée."
        ),
    )

    class Meta(SourceTextEditForm.Meta):
        fields = (*SourceTextEditForm.Meta.fields, "text")
        labels = {"text": _("Texte")}
        help_texts = {
            "text": _(
                "Collez le texte : il sera découpé en phrases, que vous vérifierez avant "
                "d’enregistrer. Les appels de note de Wikipédia ([1], [réf. nécessaire]) sont "
                "retirés."
            )
        }
        widgets = {"text": forms.Textarea(attrs={"rows": 18})}

    def clean_text(self):
        text = self.cleaned_data["text"]
        sentences = from_lines(text)
        if not sentences:
            raise ValidationError(_("Le texte est vide."), code="empty")
        if len(sentences) > MAX_SENTENCES:
            raise ValidationError(
                ngettext(
                    "Un texte compte au plus %(limit)d phrase : découpez-le en plusieurs textes.",
                    "Un texte compte au plus %(limit)d phrases : découpez-le en plusieurs textes.",
                    MAX_SENTENCES,
                )
                % {"limit": MAX_SENTENCES},
                code="too_long",
            )
        if any(len(sentence.text) > MAX_SENTENCE_LENGTH for sentence in sentences):
            raise ValidationError(
                _("Une phrase compte au plus %(limit)d caractères : vérifiez le découpage.")
                % {"limit": MAX_SENTENCE_LENGTH},
                code="sentence_too_long",
            )
        return text

    @property
    def sentences(self):
        return from_lines(self.cleaned_data["text"])


class ProjectForm(ContributionForm):
    link_fields = ("title", "description")

    class Meta:
        model = TranslationProject
        fields = ("title", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class VersionForm(ContributionForm):
    link_fields = ("style_note",)

    class Meta:
        model = TranslationVersion
        fields = ("style", "style_note")


class StepForm(ContributionForm):
    link_fields = ("message",)

    class Meta:
        model = VersionStep
        fields = ("message",)


class PublishForm(forms.Form):
    message = forms.CharField(
        label=_("Message de l’étape"),
        max_length=300,
        required=False,
        help_text=_("Facultatif ; à défaut : « Publication »."),
    )
    show_draft_steps = forms.BooleanField(
        label=_("Montrer les étapes du brouillon"),
        required=False,
        help_text=_(
            "Le public pourra suivre le cheminement de votre traduction. Ce choix est définitif."
        ),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_message(self):
        message = normalize_sentence(self.cleaned_data["message"])
        check_text_for_links(self.user, message)
        return message


class TranslationTextForm(forms.Form):
    """The Latin of one sentence."""

    text = forms.CharField(required=False, strip=False, max_length=MAX_LATIN_LENGTH)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_text(self):
        text = normalize_sentence(self.cleaned_data["text"])
        check_text_for_links(self.user, text)
        return text


class ReferenceForm(forms.Form):
    """A published version of the project, or nothing to remove the reference."""

    version = forms.ModelChoiceField(queryset=TranslationVersion.objects.none(), required=False)

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = project.versions.filter(
            state=TranslationVersion.State.PUBLISHED, is_hidden=False
        )
