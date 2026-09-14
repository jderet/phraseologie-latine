"""Django settings for the phraseologie-latine project.

Values that differ between machines come from environment variables, read from a
local .env file when present (see .env.example).
"""

from pathlib import Path

import environ
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "corpus",
    "moderation",
    "translations",
    "justifications",
    "phraseology",
    "notebook",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.TDMReservationMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: SQLite by default, PostgreSQL through DATABASE_URL.

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

# Longest duration of one query, in seconds (0: none). Set on the server for the site, so
# that a very broad search cannot hold the database; the commands that import or analyse
# the corpus run without it.
DATABASE_STATEMENT_TIMEOUT = env.int("DATABASE_STATEMENT_TIMEOUT", default=0)
if DATABASE_STATEMENT_TIMEOUT and "postgresql" in DATABASES["default"]["ENGINE"]:
    DATABASES["default"].setdefault("OPTIONS", {})["options"] = (
        f"-c statement_timeout={DATABASE_STATEMENT_TIMEOUT * 1000}"
    )

# Cache: counters of repeated login attempts, shared by every process of the site. Its
# table is created by: python manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}


# Authentication

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

# Contributions per day of a new account, until its first validated contribution.
NEW_ACCOUNT_DAILY_LIMIT = env.int("NEW_ACCOUNT_DAILY_LIMIT", default=10)

# Days after which a registration whose activation link was never used is deleted.
PENDING_SIGNUP_RETENTION_DAYS = env.int("PENDING_SIGNUP_RETENTION_DAYS", default=7)


# Internationalization: interface strings are written in French and translated in locale/.

LANGUAGE_CODE = "fr"
LANGUAGES = [
    ("fr", "Français"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"


# Email: printed to the console in development; the sending service is chosen in step 1.

MAILERS = {
    "default": {
        "BACKEND": env(
            "DJANGO_EMAIL_BACKEND",
            default="django.core.mail.backends.console.EmailBackend"
            if DEBUG
            else "django.core.mail.backends.smtp.EmailBackend",
        ),
    },
}
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="webmaster@localhost")


# Legal pages: identity of the publisher and of the host, required before public opening
# (manage.py check --deploy warns while one is missing). The address is optional for a
# publisher acting in a non-professional capacity.

LEGAL = {
    "publisher_name": env("LEGAL_PUBLISHER_NAME", default=""),
    "publisher_address": env("LEGAL_PUBLISHER_ADDRESS", default=""),
    "contact_email": env("LEGAL_CONTACT_EMAIL", default=""),
    "host_name": env("LEGAL_HOST_NAME", default=""),
    "host_address": env("LEGAL_HOST_ADDRESS", default=""),
    "host_phone": env("LEGAL_HOST_PHONE", default=""),
}

# Public repository of the code, linked from every page (AGPL-3.0, section 13).
SOURCE_CODE_URL = env("SOURCE_CODE_URL", default="https://github.com/jderet/phraseologie-latine")


# Corpus

PERSEUS_LATIN_DIR = Path(env("PERSEUS_LATIN_DIR", default=str(BASE_DIR / "canonical-latinLit")))

# Full exports of the public data (manage.py export_data), offered for download.
EXPORT_DIR = Path(env("EXPORT_DIR", default=str(BASE_DIR / "exports")))


# Content Security Policy: scripts, styles, images and fonts come from the site only, no
# page can be framed by another site, and forms post to the site only.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}


# Security for every non-debug run (production and CI).

if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # HSTS preloading is hard to undo: to be decided at public opening.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
