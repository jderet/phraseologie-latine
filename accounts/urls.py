from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from django.views.generic import TemplateView

from . import admin_views, views
from .forms import PasswordResetForm

app_name = "accounts"

urlpatterns = [
    path("compte/", views.account, name="account"),
    path("compte/inscription/", views.signup, name="signup"),
    path(
        "compte/inscription/envoyee/",
        TemplateView.as_view(template_name="accounts/signup_done.html"),
        name="signup_done",
    ),
    path("compte/activation/<uidb64>/<token>/", views.activate, name="activate"),
    path("compte/connexion/", views.LoginView.as_view(), name="login"),
    path("compte/deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("compte/supprimer/", views.delete_account, name="delete"),
    path(
        "compte/mot-de-passe/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url=reverse_lazy("accounts:password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "compte/mot-de-passe/modifie/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),
    path(
        "compte/mot-de-passe/oublie/",
        auth_views.PasswordResetView.as_view(
            form_class=PasswordResetForm,
            template_name="accounts/password_reset.html",
            email_template_name="accounts/email/password_reset_body.txt",
            subject_template_name="accounts/email/password_reset_subject.txt",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "compte/mot-de-passe/oublie/envoye/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "compte/mot-de-passe/nouveau/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "compte/mot-de-passe/nouveau/termine/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("contributeurs/<int:pk>/", views.profile, name="profile"),
    path("tableau-de-bord/", admin_views.dashboard_page, name="dashboard"),
    path(
        "tableau-de-bord/comptes/<int:pk>/mot-de-passe/",
        admin_views.set_password,
        name="dashboard_set_password",
    ),
    path(
        "tableau-de-bord/comptes/<int:pk>/lien/",
        admin_views.send_reset_link,
        name="dashboard_reset_link",
    ),
]
