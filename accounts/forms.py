from django import forms
from django.conf import settings
from django.contrib.auth import forms as auth_forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from .models import User


def current_interface_language():
    language = get_language() or settings.LANGUAGE_CODE
    return language if language in dict(settings.LANGUAGES) else settings.LANGUAGE_CODE


class SignupForm(auth_forms.BaseUserCreationForm):
    """Open registration: the account stays inactive until the email link is followed."""

    is_adult = forms.BooleanField(
        label=_("Je déclare avoir 18 ans ou plus."),
        error_messages={"required": _("La plateforme est réservée aux personnes majeures.")},
    )

    class Meta:
        model = User
        fields = ("email", "display_name")
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "display_name": forms.TextInput(attrs={"autocomplete": "nickname"}),
        }

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        existing = User.objects.filter(email__iexact=email).first()
        if existing is not None:
            if not existing.is_pending_activation:
                raise ValidationError(
                    _("Un compte existe déjà avec cette adresse e-mail."), code="email_taken"
                )
            # Signing up again replaces a registration whose link was never used:
            # only the owner of the mailbox can activate it.
            self.instance = existing
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = False
        user.is_adult = True
        user.adult_declared_at = timezone.now()
        user.interface_language = current_interface_language()
        if commit:
            user.save()
        return user


class LoginForm(auth_forms.AuthenticationForm):
    error_messages = {
        **auth_forms.AuthenticationForm.error_messages,
        "invalid_login": _(
            "Adresse e-mail ou mot de passe incorrect. Si vous venez de vous inscrire, "
            "activez d’abord votre compte avec le lien reçu par e-mail."
        ),
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].widget = forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        )


class AccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "orcid", "interface_language")


class DeleteAccountForm(forms.Form):
    password = forms.CharField(
        label=_("Mot de passe"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise ValidationError(_("Mot de passe incorrect."), code="password_incorrect")
        return password
