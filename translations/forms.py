from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from accounts.limits import check_text_for_links

from .models import (
    ChangeProposal,
    GlossaryEntry,
    ProposalReview,
    SourceProposal,
    SourceText,
    Topic,
    TranslationProject,
    TranslationVersion,
    VersionStep,
)
from .segmentation import MAX_SENTENCE_LENGTH, MAX_SENTENCES, from_lines
from .services import normalize_sentence

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


class ProposalForm(ContributionForm):
    link_fields = ("explanation",)

    class Meta:
        model = ChangeProposal
        fields = ("explanation",)
        widgets = {"explanation": forms.Textarea(attrs={"rows": 5})}


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


class SourceStateForm(forms.Form):
    """A change of the sentences of a text, written against a given state of the text."""

    state = forms.IntegerField(widget=forms.HiddenInput, min_value=0)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)


class SentenceEditForm(SourceStateForm):
    text = forms.CharField(
        label=_("Phrase"),
        max_length=MAX_SENTENCE_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    starts_paragraph = forms.BooleanField(label=_("Commence un paragraphe"), required=False)

    def clean_text(self):
        text = normalize_sentence(self.cleaned_data["text"])
        if not text:
            raise ValidationError(_("Une phrase ne peut pas être vide."), code="empty")
        check_text_for_links(self.user, text)
        return text


class SentenceSplitForm(SourceStateForm):
    parts = forms.CharField(
        label=_("Parties"),
        help_text=_("Allez à la ligne là où la phrase doit être coupée : une partie par ligne."),
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    def clean_parts(self):
        lines = (normalize_sentence(line) for line in self.cleaned_data["parts"].splitlines())
        return [line for line in lines if line]


class SentenceInsertForm(SourceStateForm):
    text = forms.CharField(label=_("Texte à ajouter"), widget=forms.Textarea(attrs={"rows": 10}))
    new_paragraph = forms.BooleanField(
        label=_("La première phrase commence un paragraphe"), required=False
    )

    def clean_text(self):
        text = self.cleaned_data["text"]
        sentences = from_lines(text)
        if not sentences:
            raise ValidationError(_("Le texte est vide."), code="empty")
        if any(len(sentence.text) > MAX_SENTENCE_LENGTH for sentence in sentences):
            raise ValidationError(
                _("Une phrase compte au plus %(limit)d caractères : vérifiez le découpage.")
                % {"limit": MAX_SENTENCE_LENGTH},
                code="sentence_too_long",
            )
        check_text_for_links(self.user, text)
        return text

    @property
    def sentences(self):
        """The sentences to add; the first starts a paragraph only if asked."""
        return [
            {
                "text": sentence.text,
                "starts_paragraph": self.cleaned_data["new_paragraph"]
                if index == 0
                else sentence.starts_paragraph,
            }
            for index, sentence in enumerate(from_lines(self.cleaned_data["text"]))
        ]


class SourceProposalForm(ContributionForm):
    """The explanation that goes with a proposal when it is sent."""

    link_fields = ("explanation",)

    explanation = forms.CharField(
        label=_("Explication"),
        max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_(
            "Pourquoi ces changements : fautes corrigées, phrases oubliées, découpage revu."
        ),
    )

    class Meta:
        model = SourceProposal
        fields = ("explanation",)


class ReferenceForm(forms.Form):
    """A published version of the project, or nothing to remove the reference."""

    version = forms.ModelChoiceField(queryset=TranslationVersion.objects.none(), required=False)

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = project.versions.filter(
            state=TranslationVersion.State.PUBLISHED, is_hidden=False
        )


class InviteForm(forms.Form):
    name = forms.CharField(
        label=_("Nom affiché ou numéro de profil"),
        max_length=80,
        help_text=_("La personne invitée accepte ou refuse ; elle voit alors votre brouillon."),
    )


class TopicForm(ContributionForm):
    link_fields = ("title", "body")

    labels = forms.MultipleChoiceField(
        label=_("Étiquettes"),
        choices=Topic.Label.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    sentence = forms.IntegerField(
        label=_("Phrase concernée"),
        required=False,
        min_value=1,
        help_text=_("Facultatif : son numéro dans le texte source."),
    )

    class Meta:
        model = Topic
        fields = ("title", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.segments = list(project.source_text.segments.current())
        self.fields["sentence"].max_value = len(self.segments)
        if self.instance.pk:
            self.initial["labels"] = self.instance.labels
            if self.instance.segment_id:
                numbers = {segment.pk: number for number, segment in enumerate(self.segments, 1)}
                self.initial["sentence"] = numbers.get(self.instance.segment_id)

    def clean_sentence(self):
        number = self.cleaned_data["sentence"]
        if number is None:
            return None
        if number > len(self.segments):
            raise ValidationError(_("Le texte n’a pas de phrase de ce numéro."))
        return self.segments[number - 1]

    def save(self, commit=True):
        topic = super().save(commit=False)
        topic.labels = self.cleaned_data["labels"]
        topic.segment = self.cleaned_data["sentence"]
        return topic


class GlossaryEntryForm(ContributionForm):
    link_fields = ("source_term", "latin_term", "note")

    unit_number = forms.IntegerField(
        label=_("Fiche phraséologique (numéro)"),
        required=False,
        min_value=1,
        help_text=_("Facultatif : le numéro de la fiche, par exemple 12 pour …/fiches/12/."),
    )
    neologism_number = forms.IntegerField(
        label=_("Néologisme (numéro)"),
        required=False,
        min_value=1,
        help_text=_("Facultatif : le numéro de la page du néologisme."),
    )

    class Meta:
        model = GlossaryEntry
        fields = ("source_term", "latin_term", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault("unit_number", self.instance.unit_id)
        self.initial.setdefault("neologism_number", self.instance.neologism_id)

    def _visible(self, model, number):
        from moderation.registry import can_view

        if number is None:
            return None
        obj = model.objects.filter(pk=number).first()
        if obj is None or not can_view(self.user, obj):
            raise ValidationError(_("Aucune page accessible ne porte ce numéro."))
        return obj

    def clean_unit_number(self):
        from phraseology.models import Unit

        return self._visible(Unit, self.cleaned_data["unit_number"])

    def clean_neologism_number(self):
        from phraseology.models import Neologism

        return self._visible(Neologism, self.cleaned_data["neologism_number"])

    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.unit = self.cleaned_data["unit_number"]
        entry.neologism = self.cleaned_data["neologism_number"]
        return entry


class SentenceCommentForm(forms.Form):
    text = forms.CharField(
        label=_("Commentaire"),
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("@Nom prévient quelqu’un."),
    )


class ReplaceForm(forms.Form):
    find = forms.CharField(label=_("Chercher"), max_length=200)
    replace = forms.CharField(label=_("Remplacer par"), max_length=200, required=False)
    whole_word = forms.BooleanField(label=_("Mot entier"), required=False)
    match_case = forms.BooleanField(label=_("Respecter les majuscules"), required=False)
    ignore_macrons = forms.BooleanField(
        label=_("Ignorer les macrons (a trouve aussi ā)"), required=False, initial=True
    )


class ProposalReviewForm(forms.Form):
    verdict = forms.ChoiceField(
        label=_("Votre avis"),
        choices=ProposalReview.Verdict.choices,
        widget=forms.RadioSelect,
        initial=ProposalReview.Verdict.COMMENT,
    )
    text = forms.CharField(
        label=_("Commentaire"),
        max_length=3000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Obligatoire, sauf pour approuver."),
    )
