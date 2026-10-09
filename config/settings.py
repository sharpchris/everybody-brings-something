"""Django settings for Everybody Brings Something.

All deploy-specific values come from environment variables (see README).
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    """True for 1/true/yes/on. Unset or empty (e.g. `HTTPS=` in an .env file) means the default."""
    value = os.environ.get(name, "").strip().lower()
    return default if not value else value in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DEBUG", default=False)
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("SECRET_KEY must be set when DEBUG is off")
    SECRET_KEY = "dev-insecure-secret-key"

# Visiting any page with ?admin=<ADMIN_KEY> unlocks admin mode. Empty disables admin.
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
if ADMIN_KEY and not DEBUG and len(ADMIN_KEY) < 20:
    raise RuntimeError("ADMIN_KEY must be at least 20 characters when DEBUG is off")

# The public address people use, e.g. https://signup.example.org or http://192.168.1.20:8000.
# It sets the allowed host, the trusted CSRF origin and (by default) whether cookies are HTTPS-only.
ON_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT"))
SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")
if not SITE_URL and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    SITE_URL = f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if SITE_URL:
    _site = urlsplit(SITE_URL)
    if (
        _site.scheme not in {"http", "https"}
        or not _site.hostname
        or _site.username
        or _site.path not in {"", "/"}
        or _site.query
        or _site.fragment
    ):
        raise ImproperlyConfigured(f"SITE_URL must look like https://example.org, got {SITE_URL!r}")
    ALLOWED_HOSTS.append(_site.hostname)
    # Browsers omit default ports in the Origin header, so the trusted origin must too.
    _default_port = {"http": 80, "https": 443}[_site.scheme]
    _port = f":{_site.port}" if _site.port and _site.port != _default_port else ""
    CSRF_TRUSTED_ORIGINS.append(f"{_site.scheme}://{_site.hostname}{_port}")
# Local access and the container healthcheck always work.
ALLOWED_HOSTS += ["localhost", "127.0.0.1", "[::1]"]
if ON_RAILWAY:
    ALLOWED_HOSTS.append("healthcheck.railway.app")  # Railway's healthcheck Host header

# Trust X-Forwarded-Proto from a reverse proxy that terminates TLS. Only enable when the
# app is reachable solely through that proxy, or clients could spoof the header.
BEHIND_PROXY = env_bool("BEHIND_PROXY", default=ON_RAILWAY)
# HTTPS-only cookies and HSTS. On by default whenever the site is served over https
# (an https SITE_URL or trusted origin, or a TLS-terminating proxy); off for plain-HTTP
# installs such as a home network.
_served_over_https = SITE_URL.startswith("https://") or BEHIND_PROXY or any(
    origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS
)
HTTPS = not DEBUG and env_bool("HTTPS", default=_served_over_https)


def env_int(name, default):
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


# Light anti-abuse limits for attendees (organizers editing the sheet aren't limited).
# Signups one person can make on a single unlimited item, e.g. "Drinks".
MAX_CLAIMS_PER_ITEM = env_int("MAX_CLAIMS_PER_ITEM", 5)
# Items one person can add to a single category with "Bring something else".
MAX_CUSTOM_ITEMS_PER_ATTENDEE = env_int("MAX_CUSTOM_ITEMS_PER_ATTENDEE", 3)
# New attendee profiles per client IP per hour (counted per process, in Django's cache).
NEW_ATTENDEES_PER_HOUR = env_int("NEW_ATTENDEES_PER_HOUR", 30)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "events",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "events.middleware.AttendeeCookieMiddleware",
    "events.middleware.AdminKeyMiddleware",
    "events.middleware.SiteSettingsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "events.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_PATH = Path(os.environ.get("DATABASE_PATH") or BASE_DIR / "db.sqlite3")
# Fail loudly rather than let SQLite error later (or write to an ephemeral
# disk) when the data volume isn't mounted where DATABASE_PATH expects.
if not DATABASE_PATH.parent.is_dir():
    raise ImproperlyConfigured(
        f"DATABASE_PATH directory {DATABASE_PATH.parent} does not exist (is the volume mounted?)"
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATABASE_PATH,
        "OPTIONS": {
            # IMMEDIATE takes the write lock at BEGIN so check-then-insert
            # (slot limits) cannot race between workers.
            "transaction_mode": "IMMEDIATE",
            "timeout": 5,
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=5000;"
                "PRAGMA foreign_keys=ON;"
            ),
        },
    }
}

SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # admin stays unlocked for 30 days

ATTENDEE_COOKIE_NAME = "ebs_aid"
ATTENDEE_COOKIE_AGE = 60 * 60 * 24 * 365 * 2

LANGUAGE_CODE = "en-us"
# Default for new installs; admins change the live time zone under Site settings.
TIME_ZONE = os.environ.get("TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
# Usually the proxy redirects HTTP to HTTPS. The app can only tell a request was HTTPS
# when it trusts the proxy's header; without that, redirecting would loop forever.
# Healthchecks probe over plain HTTP, so /health/ never redirects.
SECURE_SSL_REDIRECT = HTTPS and BEHIND_PROXY and env_bool("SECURE_SSL_REDIRECT", default=False)
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
# Modest HSTS (30 days, no subdomains/preload) keeps a domain change reversible.
# Django sends HSTS only on requests it knows are HTTPS, i.e. with BEHIND_PROXY (or TLS in-app).
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 30)) if HTTPS else 0

X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
