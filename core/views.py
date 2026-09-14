from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods

from accounts.roles import is_administrator
from phraseology.models import Kind

from . import legal
from .forms import GuideForm
from .guide import publish_guide, render_guide
from .models import GuideVersion

# User agents of robots that collect pages to train models (search robots are not listed).
TRAINING_AGENTS = [
    "GPTBot",
    "ClaudeBot",
    "anthropic-ai",
    "CCBot",
    "Google-Extended",
    "Applebot-Extended",
    "meta-externalagent",
    "FacebookBot",
    "Bytespider",
    "cohere-training-data-crawler",
    "AI2Bot",
    "PanguBot",
    "Diffbot",
]


def home(request):
    return render(request, "core/home.html")


def _legal_page(request, template, **context):
    context.update(legal=settings.LEGAL, incomplete=bool(legal.missing_fields()))
    return render(request, template, context)


@require_GET
def legal_notice(request):
    return _legal_page(request, "core/legal_notice.html")


@require_GET
def privacy(request):
    return _legal_page(
        request, "core/privacy.html", retention_days=settings.PENDING_SIGNUP_RETENTION_DAYS
    )


@require_GET
def terms(request):
    return _legal_page(request, "core/terms.html")


@require_GET
def robots_txt(request):
    return render(
        request,
        "core/robots.txt",
        {"training_agents": TRAINING_AGENTS},
        content_type="text/plain; charset=utf-8",
    )


@require_GET
def tdmrep(request):
    """Text and data mining reservation for the whole site (W3C TDMRep)."""
    return JsonResponse([{"location": "/", "tdm-reservation": 1}], safe=False)


@require_GET
def guide(request, number=None):
    """The annotation guide: its latest version, or an earlier one; every version is dated."""
    versions = GuideVersion.objects.select_related("published_by")
    latest = versions.first()
    version = latest if number is None else get_object_or_404(versions, number=number)
    return render(
        request,
        "core/guide.html",
        {
            "version": version,
            "latest": latest,
            "html": render_guide(version.text) if version else "",
            "versions": versions,
            "kinds": Kind.choices,
            "can_publish": is_administrator(request.user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def guide_publish(request):
    if not is_administrator(request.user):
        raise PermissionDenied
    latest = GuideVersion.objects.first()
    form = GuideForm(request.POST or None, initial={"text": latest.text if latest else ""})
    if request.method == "POST" and form.is_valid():
        version = publish_guide(
            form.cleaned_data["text"], form.cleaned_data["summary"], request.user
        )
        messages.success(request, _("La nouvelle version du guide est publiée."))
        return redirect(version)
    return render(request, "core/guide_publish.html", {"form": form})
