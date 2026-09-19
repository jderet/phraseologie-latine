from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def check_signup_verification(app_configs, **kwargs):
    """Never go online with e-mail verification switched off."""
    if settings.SIGNUP_SKIP_EMAIL_VERIFICATION and not settings.DEBUG:
        return [
            Error(
                "SIGNUP_SKIP_EMAIL_VERIFICATION is on while DEBUG is off.",
                hint="Remove SIGNUP_SKIP_EMAIL_VERIFICATION from the environment.",
                id="accounts.E001",
            )
        ]
    return []
