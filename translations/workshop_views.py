"""Pages of the translation workshop around the versions: help, tabs of a project."""

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .models import TranslationProject
from .templatetags.workshop_tags import FIRST_STEPS_COOKIE
from .views import _paginate, _visible
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
