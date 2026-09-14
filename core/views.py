from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import legal

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
