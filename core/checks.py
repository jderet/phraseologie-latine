from django.core import checks

from . import legal


@checks.register(checks.Tags.security, deploy=True)
def check_legal_pages(app_configs, **kwargs):
    """The legal pages must name the publisher and the host before the site goes online."""
    missing = legal.missing_fields()
    if not missing:
        return []
    return [
        checks.Warning(
            f"The legal pages are incomplete: {', '.join(missing)}.",
            hint="Set the LEGAL_* environment variables (see .env.example).",
            id="core.W001",
        )
    ]
