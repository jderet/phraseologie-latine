from django.conf import settings


def site(request):
    """Values shown on every page."""
    return {"source_code_url": settings.SOURCE_CODE_URL}
