from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.roles import is_administrator
from accounts.views import set_language_cookie
from corpus.models import Author
from corpus.search import quotation
from phraseology.models import Attestation, Kind, Unit

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


# The home page shows live figures; they are counted at most once every five minutes.
HOME_COUNTS_KEY = "home-counts"
HOME_COUNTS_SECONDS = 300


def home_counts():
    counts = cache.get(HOME_COUNTS_KEY)
    if counts is None:
        public_units = Unit.objects.filter(status=Unit.Status.VALIDATED, is_hidden=False)
        counts = {
            "units": public_units.count(),
            "attestations": Attestation.objects.filter(
                unit__in=public_units,
                level=Attestation.Level.VALIDATED,
                status=Attestation.Status.VALIDATED,
                is_withdrawn=False,
                is_hidden=False,
            ).count(),
            "authors": Author.objects.count(),
        }
        cache.set(HOME_COUNTS_KEY, counts, HOME_COUNTS_SECONDS)
    return counts


def home_showcase():
    """One public entry with a chosen, human-validated example, quoted on the home page."""
    attestation = (
        Attestation.objects.filter(
            is_example=True,
            is_withdrawn=False,
            is_hidden=False,
            level=Attestation.Level.VALIDATED,
            status=Attestation.Status.VALIDATED,
            unit__status=Unit.Status.VALIDATED,
            unit__is_hidden=False,
        )
        .select_related("unit", "passage__edition__work__author")
        .first()
    )
    if attestation is None:
        return None
    attestation.quotation = quotation(list(attestation.tokens.all()))
    return attestation


def home(request):
    return render(request, "core/home.html", {"counts": home_counts(), "showcase": home_showcase()})


# The appearance choices kept in a cookie: light, dark, or following the system.
THEME_CHOICES = ("light", "auto", "dark")


@require_POST
def theme(request):
    """Remember the appearance choice in a cookie; no account and no script needed."""
    value = request.POST.get("theme")
    if value not in THEME_CHOICES:
        value = "auto"
    next_url = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = "/"
    response = redirect(next_url)
    response.set_cookie("theme", value, max_age=60 * 60 * 24 * 365, samesite="Lax")
    messages.success(request, _("Votre thème est enregistré."))
    return response


@login_required
@require_GET
def settings_page(request):
    """The page where the visitor chooses the theme and the interface language."""
    return render(request, "core/settings.html", {"theme": request.COOKIES.get("theme", "auto")})


@login_required
@require_POST
def settings_language(request):
    """Remember the chosen interface language on the account and in the cookie."""
    language = request.POST.get("language")
    if language not in dict(settings.LANGUAGES):
        language = settings.LANGUAGE_CODE
    request.user.interface_language = language
    request.user.save(update_fields=["interface_language"])
    messages.success(request, _("Votre langue est enregistrée."))
    return set_language_cookie(redirect("core:settings"), language)


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
