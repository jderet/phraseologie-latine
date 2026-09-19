"""Pages where versions work together: update a copy from its original, propose to the original,
review proposals, label and restore steps, the network of copies, who wrote what."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods

from .sync import take_upstream, upstream_changes
from .views import _own_version


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
