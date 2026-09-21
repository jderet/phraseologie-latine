"""Roles in a project: an editor invites, the person accepts or declines, an editor removes
them; a member may also leave. Every change is recorded as a revision."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from accounts.models import User
from activity.models import Verb
from activity.services import auto_follow, record
from moderation.services import save_with_revision

from .models import ProjectMember, TranslationProject, is_editor

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


def _forget_roles(project):
    project.__dict__.pop("_role_ids", None)


@transaction.atomic
def invite(project, author, invitee, role=ProjectMember.Role.TRANSLATOR):
    """An editor of a project gives someone a role in it."""
    project = TranslationProject.objects.select_for_update().get(pk=project.pk)
    if not author.is_active or not is_editor(author, project):
        raise PermissionDenied
    if role not in ProjectMember.Role.values:
        raise ValueError("Unknown role.")
    if invitee.pk == project.created_by_id:
        raise ValidationError(gettext("Cette personne a créé le projet."), code="self")
    if not invitee.is_active:
        raise ValidationError(gettext("Ce compte n’est pas actif."), code="inactive")
    member = ProjectMember.objects.filter(project=project, user=invitee).first()
    if member is not None and member.status in (
        ProjectMember.Status.INVITED,
        ProjectMember.Status.ACTIVE,
    ):
        raise ValidationError(
            gettext("Cette personne est déjà invitée ou membre du projet."), code="already"
        )
    current = project.members.filter(
        status__in=[ProjectMember.Status.INVITED, ProjectMember.Status.ACTIVE]
    ).count()
    if current >= MAX_MEMBERS:
        raise ValidationError(
            gettext("Un projet compte au plus %(count)d membres.") % {"count": MAX_MEMBERS},
            code="too_many",
        )
    if member is None:
        member = ProjectMember(project=project, user=invitee)
    member.role = role
    member.invited_by = author
    member.invited_at = timezone.now()
    member.decided_at = None
    member.status = ProjectMember.Status.INVITED
    save_with_revision(member, author, comment=gettext("Invitation"))
    record(author, Verb.MEMBER_INVITED, member, recipients=[invitee.pk], notify_followers=False)
    return member


@transaction.atomic
def answer(member, user, accept):
    """The person invited accepts or declines."""
    member = ProjectMember.objects.select_for_update().get(pk=member.pk)
    if user.pk != member.user_id or not user.is_active:
        raise PermissionDenied
    if member.status != ProjectMember.Status.INVITED:
        raise ValidationError(gettext("Cette invitation n’est plus en attente."), code="answered")
    member.status = ProjectMember.Status.ACTIVE if accept else ProjectMember.Status.DECLINED
    member.decided_at = timezone.now()
    comment = gettext("Invitation acceptée") if accept else gettext("Invitation refusée")
    save_with_revision(member, user, comment=comment)
    _forget_roles(member.project)
    if accept:
        auto_follow(user, member.project)
    verb = Verb.MEMBER_JOINED if accept else Verb.MEMBER_DECLINED
    record(user, verb, member, recipients=[member.invited_by_id], notify_followers=False)
    return member


@transaction.atomic
def remove(member, user):
    """An editor removes a member or withdraws an invitation; a member may leave."""
    member = ProjectMember.objects.select_for_update().select_related("project").get(pk=member.pk)
    if user.pk != member.user_id and not is_editor(user, member.project):
        raise PermissionDenied
    if member.status not in (ProjectMember.Status.INVITED, ProjectMember.Status.ACTIVE):
        raise ValidationError(gettext("Cette personne n’est plus membre."), code="removed")
    member.status = ProjectMember.Status.REMOVED
    member.decided_at = timezone.now()
    comment = gettext("Départ") if user.pk == member.user_id else gettext("Retrait")
    save_with_revision(member, user, comment=comment)
    _forget_roles(member.project)
    return member


@transaction.atomic
def change_role(member, user, role):
    """An editor changes the role of an active member."""
    member = ProjectMember.objects.select_for_update().select_related("project").get(pk=member.pk)
    if not user.is_active or not is_editor(user, member.project):
        raise PermissionDenied
    if role not in ProjectMember.Role.values:
        raise ValueError("Unknown role.")
    if not member.is_active:
        raise ValidationError(gettext("Cette personne n’est pas membre."), code="inactive")
    member.role = role
    save_with_revision(member, user, comment=member.get_role_display())
    _forget_roles(member.project)
    return member


def active_members(project):
    return project.members.filter(status=ProjectMember.Status.ACTIVE).select_related("user")


def writing_members(project):
    """The members who write the translation: editors and translators."""
    return active_members(project).filter(
        role__in=[ProjectMember.Role.EDITOR, ProjectMember.Role.TRANSLATOR]
    )


def pending_invitations(user):
    """Invitations waiting for the user's answer."""
    if not user.is_authenticated:
        return ProjectMember.objects.none()
    return ProjectMember.objects.filter(
        user=user, status=ProjectMember.Status.INVITED, project__is_hidden=False
    ).select_related("project", "invited_by")
