"""Pages where versions work together: update a copy from its original, propose to the original,
review proposals, label and restore steps, the network of copies, who wrote what."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods

from moderation.registry import can_view

from .forms import ProposalForm
from .models import ChangeProposal  # noqa: F401 - the form builds one
from .permissions import can_propose
from .services import create_proposal
from .sync import differences_with_original, take_upstream, upstream_changes
from .views import _contribute, _own_version


@login_required
@require_http_methods(["GET", "POST"])
def sync_copy(request, pk):
    """What the original changed since the copy, to take sentence by sentence."""
    version = _own_version(request.user, pk)
    if version.copied_from_id is None:
        messages.info(request, _("Cette version n’est pas une copie."))
        return redirect(version)
    latest, changes = upstream_changes(request.user, version)
    if request.method == "POST":
        chosen = {int(value) for value in request.POST.getlist("phrase") if value.isdigit()}
        taken = take_upstream(request.user, version, chosen)
        messages.success(
            request,
            ngettext(
                "%(count)d phrase reprise de l’originale.",
                "%(count)d phrases reprises de l’originale.",
                taken,
            )
            % {"count": taken},
        )
        return redirect("translations:version_edit", version.pk)
    return render(
        request,
        "translations/sync_copy.html",
        {
            "version": version,
            "project": version.project,
            "original": version.copied_from.version,
            "base": version.synced_to or version.copied_from,
            "latest": latest,
            "changes": changes,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def propose_to_original(request, pk):
    """Prepare a proposal to the original with the sentences where the copy differs."""
    user = request.user
    version = _own_version(user, pk)
    if version.copied_from_id is None:
        messages.info(request, _("Cette version n’est pas une copie."))
        return redirect(version)
    original = version.copied_from.version
    if not can_propose(user, original) or not can_view(user, original):
        messages.error(request, _("Vous ne pouvez pas proposer de modifications à l’originale."))
        return redirect(version)
    step, rows = differences_with_original(user, version)
    form = ProposalForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        chosen = set(request.POST.getlist("phrase"))
        texts = {
            segment: mine for segment, _n, _theirs, mine, _c in rows if str(segment.pk) in chosen
        }
        proposal = form.save(commit=False)
        proposal.version = original
        try:
            proposal, saved = _contribute(request, create_proposal, proposal, user, texts)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            if saved:
                messages.success(
                    request, _("La proposition est envoyée à l’auteur de l’originale.")
                )
                return redirect(proposal)
    return render(
        request,
        "translations/propose_to_original.html",
        {
            "version": version,
            "project": version.project,
            "original": original,
            "step": step,
            "rows": rows,
            "form": form,
        },
    )
