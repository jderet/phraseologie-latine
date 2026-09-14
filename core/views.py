from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

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
