"""Administrators' dashboard: figures, queues, activity and accounts."""

import logging

from django.contrib import messages
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from . import dashboard
from .forms import PasswordResetForm
from .models import User
from .roles import is_administrator, role_labels
from .throttle import ADMIN_PASSWORD_CHANGES

logger = logging.getLogger("accounts.admin")

USERS_PER_PAGE = 50


def _require_administrator(request):
    if not is_administrator(request.user):
        raise PermissionDenied


@login_required
def dashboard_page(request):
    _require_administrator(request)
    users = User.objects.order_by("-date_joined")
    query = request.GET.get("q", "").strip()
    if query:
        users = users.filter(Q(email__icontains=query) | Q(display_name__icontains=query))
    page = Paginator(users, USERS_PER_PAGE).get_page(request.GET.get("page"))
    rows = [(user, role_labels(user)) for user in page]
    return render(
        request,
        "accounts/dashboard.html",
        {
            "figures": dashboard.key_figures(),
            "queues": dashboard.queues(),
            "activity": dashboard.recent_activity(),
            "technical": dashboard.technical_state(),
            "page": page,
            "rows": rows,
            "query": query,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def set_password(request, pk):
    """Give an account a new password chosen by the administrator; nobody can read the old one."""
    _require_administrator(request)
    target = get_object_or_404(User, pk=pk, anonymized_at=None)
    if request.method == "POST":
        if ADMIN_PASSWORD_CHANGES.is_blocked(request.user.email):
            messages.error(request, _("Trop de changements de mot de passe. Réessayez plus tard."))
            return redirect("accounts:dashboard")
        form = auth_forms.SetPasswordForm(target, request.POST)
        if form.is_valid():
            ADMIN_PASSWORD_CHANGES.hit(request.user.email)
            form.save()
            logger.info(
                "Administrator %s set a new password for user %s.", request.user.pk, target.pk
            )
            messages.success(
                request,
                _("Nouveau mot de passe enregistré pour %(name)s.") % {"name": target.email},
            )
            return redirect("accounts:dashboard")
    else:
        form = auth_forms.SetPasswordForm(target)
    return render(request, "accounts/dashboard_password.html", {"form": form, "target": target})


@login_required
@require_POST
def send_reset_link(request, pk):
    _require_administrator(request)
    target = get_object_or_404(User, pk=pk, anonymized_at=None, is_active=True)
    form = PasswordResetForm({"email": target.email})
    if form.is_valid():
        form.save(
            request=request,
            email_template_name="accounts/email/password_reset_body.txt",
            subject_template_name="accounts/email/password_reset_subject.txt",
        )
    logger.info("Administrator %s sent a reset link to user %s.", request.user.pk, target.pk)
    messages.success(
        request, _("Lien de réinitialisation envoyé à %(email)s.") % {"email": target.email}
    )
    return redirect("accounts:dashboard")
