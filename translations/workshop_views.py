"""Pages of the translation workshop around the versions: help, tabs of a project."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from activity.feeds import project_feed
from moderation.registry import can_view

from . import members as member_services
from .forms import InviteForm
from .models import TranslationProject, TranslationVersion, VersionMember, is_version_writer
from .permissions import can_manage
from .templatetags.workshop_tags import FIRST_STEPS_COOKIE
from .views import _contribute, _paginate, _visible
from .workshop import visible_proposals


@require_GET
def help_page(request):
    return render(request, "translations/help.html")


def _safe_next(request, fallback="/"):
    next_url = request.POST.get("next") or request.GET.get("next") or fallback
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return fallback
    return next_url


@require_POST
def hide_first_steps(request):
    """Close the first steps box for good, remembered in a cookie; no account needed."""
    response = redirect(_safe_next(request))
    response.set_cookie(FIRST_STEPS_COOKIE, "hidden", max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


def project_proposals(request, pk):
    """All the change proposals made to the versions of a project, open ones first."""
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    proposals = visible_proposals(request.user, project)
    return render(
        request,
        "translations/project_proposals.html",
        {
            "project": project,
            "source": project.source_text,
            "page": _paginate(request, proposals),
        },
    )


def project_activity(request, pk):
    """What happened lately in a project: publications, steps, proposals, messages."""
    project = _visible(request.user, TranslationProject.objects.select_related("source_text"), pk)
    return render(
        request,
        "translations/project_activity.html",
        {"project": project, "events": project_feed(request.user, project)},
    )


# Co-authors


def _members_version(user, pk):
    """A version the user may see, or one they are invited to co-author."""
    version = get_object_or_404(
        TranslationVersion.objects.select_related("project", "author"), pk=pk
    )
    invited = (
        user.is_authenticated
        and version.members.filter(user=user, status=VersionMember.Status.INVITED).exists()
    )
    if not (can_view(user, version) or invited):
        raise Http404
    return version


@require_http_methods(["GET", "POST"])
def version_members(request, pk):
    """The co-authors of a version; its author invites and removes them."""
    user = request.user
    version = _members_version(user, pk)
    manager = can_manage(user, version)
    form = InviteForm(request.POST or None)
    if request.method == "POST":
        if not manager:
            raise Http404
        if form.is_valid():
            try:
                invitee = member_services.find_invitee(form.cleaned_data["name"])
                member, saved = _contribute(request, member_services.invite, version, user, invitee)
            except ValidationError as error:
                form.add_error("name", error)
            else:
                if saved:
                    messages.success(
                        request,
                        _("%(name)s est invité : il ou elle doit accepter l’invitation.")
                        % {"name": member.user.public_name},
                    )
                    return redirect("translations:version_members", version.pk)
    shown = [
        member
        for member in version.members.select_related("user", "invited_by")
        if can_view(user, member)
        and (member.status in (VersionMember.Status.INVITED, VersionMember.Status.ACTIVE))
    ]
    own = next((member for member in shown if member.user_id == user.pk), None)
    return render(
        request,
        "translations/version_members.html",
        {
            "version": version,
            "project": version.project,
            "members": shown,
            "own": own,
            "can_manage": manager,
            "is_writer": is_version_writer(user, version),
            "form": form if manager else None,
        },
    )


@login_required
@require_POST
def member_answer(request, pk):
    member = get_object_or_404(VersionMember.objects.select_related("version"), pk=pk)
    decision = request.POST.get("decision")
    if decision not in ("accept", "decline"):
        return HttpResponseBadRequest()
    try:
        member_services.answer(member, request.user, accept=decision == "accept")
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("translations:version_members", member.version_id)
    if decision == "accept":
        messages.success(request, _("Vous êtes co-auteur de cette version."))
        return redirect("translations:version_edit", member.version_id)
    messages.success(request, _("L’invitation est refusée."))
    return redirect("translations:project", member.version.project_id)


@login_required
@require_POST
def member_remove(request, pk):
    member = get_object_or_404(VersionMember.objects.select_related("version"), pk=pk)
    try:
        member_services.remove(member, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        if request.user.pk == member.user_id:
            messages.success(request, _("Vous n’êtes plus co-auteur de cette version."))
            return redirect("translations:project", member.version.project_id)
        messages.success(request, _("La personne n’est plus co-autrice de cette version."))
    return redirect("translations:version_members", member.version_id)
