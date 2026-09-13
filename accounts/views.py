from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from .forms import AccountForm, DeleteAccountForm, LoginForm, SignupForm
from .models import User
from .roles import role_labels
from .services import activate_user, anonymize_user, send_activation_email
from .tokens import activation_token_generator


def set_language_cookie(response, language):
    """Remember the interface language the same way Django's set_language view does."""
    response.set_cookie(
        settings.LANGUAGE_COOKIE_NAME,
        language,
        max_age=settings.LANGUAGE_COOKIE_AGE,
        path=settings.LANGUAGE_COOKIE_PATH,
        domain=settings.LANGUAGE_COOKIE_DOMAIN,
        secure=settings.LANGUAGE_COOKIE_SECURE,
        httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
        samesite=settings.LANGUAGE_COOKIE_SAMESITE,
    )
    return response


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:account")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            send_activation_email(request, user)
            return redirect("accounts:signup_done")
    else:
        form = SignupForm()
    return render(request, "accounts/signup.html", {"form": form})


def _user_from_uidb64(uidb64):
    try:
        return User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


@require_http_methods(["GET", "POST"])
def activate(request, uidb64, token):
    """Show a confirmation button, then activate on POST.

    Activating on GET would log in whoever opens the link first, including the link
    checkers of some email services.
    """
    user = _user_from_uidb64(uidb64)
    if user is None or user.is_active or not activation_token_generator.check_token(user, token):
        return render(request, "accounts/activation_invalid.html", status=400)
    if request.method == "POST":
        activate_user(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Votre compte est activé. Bienvenue !"))
        return set_language_cookie(redirect("accounts:account"), user.interface_language)
    return render(request, "accounts/activate.html", {"activated_user": user})


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        return set_language_cookie(response, form.get_user().interface_language)


@login_required
@require_http_methods(["GET", "POST"])
def account(request):
    if request.method == "POST":
        form = AccountForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()
            messages.success(request, _("Vos informations sont enregistrées."))
            return set_language_cookie(redirect("accounts:account"), user.interface_language)
    else:
        form = AccountForm(instance=request.user)
    return render(
        request, "accounts/account.html", {"form": form, "roles": role_labels(request.user)}
    )


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    if request.method == "POST":
        form = DeleteAccountForm(request.user, request.POST)
        if form.is_valid():
            anonymize_user(request.user)
            logout(request)
            messages.success(
                request,
                _("Votre compte est supprimé. Vos contributions restent, sans votre nom."),
            )
            return redirect("core:home")
    else:
        form = DeleteAccountForm(request.user)
    return render(request, "accounts/delete.html", {"form": form})


def profile(request, pk):
    profile_user = get_object_or_404(User, pk=pk, is_active=True)
    return render(
        request,
        "accounts/profile.html",
        {"profile_user": profile_user, "roles": role_labels(profile_user)},
    )
