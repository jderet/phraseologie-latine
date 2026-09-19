"""Co-authors of a version: the author invites them, they accept or decline, the author removes
them; a co-author may also leave. Every change is recorded as a revision."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.models import User
from activity.models import Verb
from activity.services import auto_follow, record
from moderation.services import save_with_revision

from .models import TranslationVersion, VersionMember

MAX_MEMBERS = 20


def find_invitee(query):
    """The active account named ``query``: its displayed name, or its profile number.

    Raise ValidationError when no account, or several, match.
    """
    query = (query or "").strip().lstrip("#")
    accounts = User.objects.filter(is_active=True, anonymized_at__isnull=True)
    if query.isdigit():
        found = list(accounts.filter(pk=int(query)))
    else:
        found = list(accounts.filter(display_name__iexact=query)[:2])
    if not found:
        raise ValidationError(gettext("Aucun compte ne porte ce nom."), code="not_found")
    if len(found) > 1:
        raise ValidationError(
            gettext(
                "Plusieurs comptes portent ce nom : indiquez le numéro de sa page de profil "
                "(par exemple 12 pour …/contributeurs/12/)."
            ),
            code="ambiguous",
        )
    return found[0]


def _forget_writers(version):
    version.__dict__.pop("_writer_ids", None)


@transaction.atomic
def invite(version, author, invitee):
    """The author of a version invites someone to co-author it."""
    version = TranslationVersion.objects.select_for_update().get(pk=version.pk)
    if author.pk != version.author_id or not author.is_active:
        raise PermissionDenied
    if invitee.pk == version.author_id:
        raise ValidationError(gettext("Vous êtes déjà l’auteur de cette version."), code="self")
    if not invitee.is_active:
        raise ValidationError(gettext("Ce compte n’est pas actif."), code="inactive")
    member = VersionMember.objects.filter(version=version, user=invitee).first()
    if member is not None and member.status in (
        VersionMember.Status.INVITED,
        VersionMember.Status.ACTIVE,
    ):
        raise ValidationError(
            gettext("Cette personne est déjà invitée ou co-autrice."), code="already"
        )
    current = version.members.filter(
        status__in=[VersionMember.Status.INVITED, VersionMember.Status.ACTIVE]
    ).count()
    if current >= MAX_MEMBERS:
        raise ValidationError(
            gettext("Une version a au plus %(count)d co-auteurs.") % {"count": MAX_MEMBERS},
            code="too_many",
        )
    if member is None:
        member = VersionMember(version=version, user=invitee)
    member.invited_by = author
    member.invited_at = timezone.now()
    member.decided_at = None
    member.status = VersionMember.Status.INVITED
    save_with_revision(member, author, comment=gettext("Invitation"))
    record(author, Verb.MEMBER_INVITED, member, recipients=[invitee.pk], notify_followers=False)
    return member


@transaction.atomic
def answer(member, user, accept):
    """The person invited accepts or declines."""
    member = VersionMember.objects.select_for_update().get(pk=member.pk)
    if user.pk != member.user_id or not user.is_active:
        raise PermissionDenied
    if member.status != VersionMember.Status.INVITED:
        raise ValidationError(gettext("Cette invitation n’est plus en attente."), code="answered")
    member.status = VersionMember.Status.ACTIVE if accept else VersionMember.Status.DECLINED
    member.decided_at = timezone.now()
    comment = gettext("Invitation acceptée") if accept else gettext("Invitation refusée")
    save_with_revision(member, user, comment=comment)
    _forget_writers(member.version)
    if accept:
        auto_follow(user, member.version)
    verb = Verb.MEMBER_JOINED if accept else Verb.MEMBER_DECLINED
    record(user, verb, member, recipients=[member.version.author_id], notify_followers=False)
    return member


@transaction.atomic
def remove(member, user):
    """The author removes a co-author or withdraws an invitation; a co-author may leave."""
    member = VersionMember.objects.select_for_update().select_related("version").get(pk=member.pk)
    if user.pk not in (member.version.author_id, member.user_id):
        raise PermissionDenied
    if member.status not in (VersionMember.Status.INVITED, VersionMember.Status.ACTIVE):
        raise ValidationError(gettext("Cette personne n’est plus co-autrice."), code="removed")
    member.status = VersionMember.Status.REMOVED
    member.decided_at = timezone.now()
    comment = gettext("Départ") if user.pk == member.user_id else gettext("Retrait")
    save_with_revision(member, user, comment=comment)
    _forget_writers(member.version)
    return member


def active_members(version):
    return version.members.filter(status=VersionMember.Status.ACTIVE).select_related("user")


def pending_invitations(user):
    """Invitations waiting for the user's answer."""
    if not user.is_authenticated:
        return VersionMember.objects.none()
    return VersionMember.objects.filter(
        user=user, status=VersionMember.Status.INVITED, version__is_hidden=False
    ).select_related("version__project", "version__author", "invited_by")
