"""Account operations shared by views, the admin and management commands."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User
from .roles import CONTRIBUTOR
from .tokens import activation_token_generator


def send_activation_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = activation_token_generator.make_token(user)
    context = {
        "user": user,
        "activation_url": request.build_absolute_uri(
            reverse("accounts:activate", args=[uid, token])
        ),
    }
    subject = render_to_string("accounts/email/activation_subject.txt", context, request)
    body = render_to_string("accounts/email/activation_body.txt", context, request)
    send_mail(" ".join(subject.split()), body, None, [user.email])


@transaction.atomic
def activate_user(user):
    user.is_active = True
    user.save(update_fields=["is_active"])
    user.groups.add(Group.objects.get(name=CONTRIBUTOR))


@transaction.atomic
def anonymize_user(user):
    """Erase personal data but keep the account row, so contributions stay (CC BY-SA)."""
    user.display_name = ""
    user.email = f"anonyme-{user.pk}@anonyme.invalid"
    user.orcid = ""
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.last_login = None
    user.set_unusable_password()
    user.anonymized_at = timezone.now()
    user.save()
    user.groups.clear()
    user.user_permissions.clear()
    # The private notebook is personal data, not a contribution: it is deleted. Imported here,
    # since the notebook application depends on the accounts.
    from notebook.services import delete_notebook

    delete_notebook(user)


@transaction.atomic
def purge_pending_signups():
    """Delete registrations whose activation link was never used, after the retention period.

    Such accounts never logged in, so they have no contribution to keep. Returns the number
    of deleted accounts.
    """
    cutoff = timezone.now() - timedelta(days=settings.PENDING_SIGNUP_RETENTION_DAYS)
    pending = User.objects.filter(
        is_active=False, last_login=None, anonymized_at=None, date_joined__lt=cutoff
    )
    count = pending.count()
    pending.delete()
    return count
