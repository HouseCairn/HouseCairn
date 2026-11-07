"""Django settings for HouseCairn.

Every setting comes from environment variables (see `.env.example` and
`docs/adr/0012-configuration-and-security-defaults.md`). The defaults are the
safe ones: `DEBUG` is off, cookies are secure, HTTPS is enforced, and nothing
is loaded from a third-party host.
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import django_stubs_ext
import environ
from csp.constants import NONE, SELF
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from housecairn.core.proxy import TrustedProxies

# Allows generic annotations such as ListView[Home] at runtime.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parents[1]

env = environ.Env()
# A local `.env` file is only a convenience for development: it fills in
# variables that are not already set, never overrides them.
if (REPO_DIR / ".env").is_file():
    env.read_env(str(REPO_DIR / ".env"), overwrite=False)

DEBUG: bool = env.bool("DEBUG", default=False)

_DEV_SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"  # noqa: S105
SECRET_KEY: str = env.str("SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is false.")
    SECRET_KEY = _DEV_SECRET_KEY

ALLOWED_HOSTS: list[str] = env.list(
    "ALLOWED_HOSTS", default=["localhost", "127.0.0.1"] if DEBUG else []
)
CSRF_TRUSTED_ORIGINS: list[str] = env.list("CSRF_TRUSTED_ORIGINS", default=[])

DATA_DIR = Path(env.str("HOUSECAIRN_DATA_DIR", default=str(REPO_DIR / "data")))

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # allauth's security-key pages use its date filters.
    "django.contrib.humanize",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django_q",
    "csp",
    "housecairn.core",
    "housecairn.accounts",
    "housecairn.homes",
    "housecairn.apitokens",
    "housecairn.events",
]

MIDDLEWARE = [
    # First: forwarding headers count only from a trusted reverse proxy, before
    # the HTTPS redirect or anything else reads them (docs/adr/0012).
    "housecairn.core.proxy.ForwardedHeadersMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves the collected static files, right after the security headers are
    # set (docs/adr/0015).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "housecairn.urls"
WSGI_APPLICATION = "housecairn.wsgi.application"
ASGI_APPLICATION = "housecairn.asgi.application"

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
                "housecairn.accounts.context_processors.signup",
                "housecairn.core.context_processors.shell",
                "housecairn.core.help.help_link",
            ],
        },
    },
]

# Database: SQLite in the data directory unless DATABASE_URL says otherwise
# (for example postgres://user:password@db.example.com:5432/housecairn).
DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default=f"sqlite:///{(DATA_DIR / 'db.sqlite3').as_posix()}"
    ),
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {
            # WAL lets the web process and the task worker read and write at once;
            # IMMEDIATE avoids "database is locked" errors on concurrent writes.
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
        }
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Internationalization: English is the source language, French ships with V1.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("fr", _("French"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
TIME_ZONE = env.str("TIME_ZONE", default="UTC")
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(env.str("STATIC_ROOT", default=str(DATA_DIR / "static")))
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(DATA_DIR / "media")))
MEDIA_URL = "media/"
# Static files are collected once, at image build time, with a content hash in
# their names and a compressed copy, then served by WhiteNoise with long-lived
# cache headers (docs/adr/0015). With DEBUG on, the hashed names are not used.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Public source repository, shown on the About screen.
HOUSECAIRN_SOURCE_URL = "https://github.com/HouseCairn/housecairn"

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "homes:list"

# Security headers and cookies (docs/adr/0012). Safe values unless DEBUG is on.
SECURE_SSL_REDIRECT: bool = env.bool("SECURE_SSL_REDIRECT", default=not DEBUG)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
HOUSECAIRN_BEHIND_TLS_PROXY: bool = env.bool("HOUSECAIRN_BEHIND_TLS_PROXY", default=False)
if HOUSECAIRN_BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Reverse proxies whose forwarding headers count: X-Forwarded-Proto above and
# X-Forwarded-For for the client address. From any other peer, these headers
# are removed by housecairn.core.proxy.ForwardedHeadersMiddleware. The loopback
# by default; set it to the proxy's address or network.
HOUSECAIRN_FORWARDED_ALLOW_IPS: list[str] = env.list(
    "HOUSECAIRN_FORWARDED_ALLOW_IPS", default=["127.0.0.1", "::1"]
)
TrustedProxies.parse(HOUSECAIRN_FORWARDED_ALLOW_IPS)  # fails at start-up if invalid
# The client address is resolved once, by that middleware, into REMOTE_ADDR:
# django-allauth's rate limits must not read X-Forwarded-For themselves.
ALLAUTH_TRUSTED_PROXY_COUNT = 0
ALLAUTH_TRUSTED_CLIENT_IP_HEADER = None
# The Host header, not X-Forwarded-Host, names the site: the proxy must pass
# Host through (Caddy and Traefik do by default; nginx: proxy_set_header Host).
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False
SECURE_HSTS_SECONDS: int = env.int("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD: bool = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_SECURE: bool = env.bool("SESSION_COOKIE_SECURE", default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE: bool = env.bool("CSRF_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
# Including subdomains in HSTS and asking for preloading are commitments for the
# whole domain, which only its owner can make: they stay opt-in, so Django's
# reminders about them are silenced (docs/adr/0012).
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Content Security Policy (docs/adr/0011): no inline script or style, nothing
# from another origin.
_form_action: list[str] = [SELF]

# Authentication: django-allauth (docs/adr/0007).
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = env.str("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_ADAPTER = "housecairn.accounts.adapters.AccountAdapter"
ACCOUNT_FORMS = {"login": "housecairn.accounts.forms.LoginForm"}
SOCIALACCOUNT_ADAPTER = "housecairn.accounts.adapters.SocialAccountAdapter"
SOCIALACCOUNT_ONLY = False
HOUSECAIRN_SIGNUP_OPEN: bool = env.bool("HOUSECAIRN_SIGNUP_OPEN", default=False)
# Sign-up through OIDC: "closed" (default) refuses an identity without an
# account, except the very first one, which becomes the instance
# administrator; "open" lets anyone the provider accepts create an account.
HOUSECAIRN_OIDC_SIGNUP: str = env.str("HOUSECAIRN_OIDC_SIGNUP", default="closed").strip().lower()
if HOUSECAIRN_OIDC_SIGNUP not in {"closed", "open"}:
    raise ImproperlyConfigured("HOUSECAIRN_OIDC_SIGNUP must be 'closed' or 'open'.")
# If set, only this address, verified by the provider, can become the first
# administrator through OIDC.
HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL: str = env.str(
    "HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL", default=""
).strip()

# Outgoing email, off until EMAIL_HOST is set. Without a server the console
# backend only prints messages, so features that need a real mailbox, such as
# password reset by email, stay hidden (accounts.services.email_is_configured).
EMAIL_HOST: str = env.str("EMAIL_HOST", default="").strip()
EMAIL_PORT: int = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER: str = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD: str = env.str("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS: bool = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL: str = env.str("DEFAULT_FROM_EMAIL", default="HouseCairn <noreply@localhost>")

MFA_SUPPORTED_TYPES = ["totp", "recovery_codes", "webauthn"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_TOTP_ISSUER = "HouseCairn"
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = DEBUG

# Generic OpenID Connect provider, enabled only when its variables are set. No
# provider is named in the code: any compliant identity provider works.
SOCIALACCOUNT_PROVIDERS: dict[str, Any] = {}
_oidc_server_url: str = env.str("OIDC_SERVER_URL", default="")
if _oidc_server_url:
    SOCIALACCOUNT_PROVIDERS["openid_connect"] = {
        "OAUTH_PKCE_ENABLED": True,
        "APPS": [
            {
                "provider_id": env.str("OIDC_PROVIDER_ID", default="oidc"),
                "name": env.str("OIDC_PROVIDER_NAME", default="Single sign-on"),
                "client_id": env.str("OIDC_CLIENT_ID"),
                "secret": env.str("OIDC_CLIENT_SECRET", default=""),
                "settings": {"server_url": _oidc_server_url},
            }
        ],
    }
    # Browsers apply form-action to the redirect that follows the sign-in form.
    _parts = urlsplit(_oidc_server_url)
    _form_action.append(f"{_parts.scheme}://{_parts.netloc}")

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [NONE],
        "script-src": [SELF],
        "style-src": [SELF],
        "img-src": [SELF, "data:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "manifest-src": [SELF],
        "form-action": _form_action,
        "frame-ancestors": [NONE],
        "base-uri": [NONE],
        "object-src": [NONE],
    },
}

# REST API (docs/adr/0004).
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "housecairn.apitokens.authentication.ApiTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "housecairn.apitokens.permissions.TokenScopePermission",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "housecairn.core.pagination.DefaultCursorPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "HouseCairn API",
    "DESCRIPTION": "Version 1 of the HouseCairn API, shared by every client.",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SERVE_INCLUDE_SCHEMA": False,
    # An `events` token posts events and reads nothing, the schema included.
    "SERVE_PERMISSIONS": [
        "rest_framework.permissions.IsAuthenticated",
        "housecairn.apitokens.permissions.TokenScopePermission",
    ],
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
}

# Background tasks: django-q2 with the ORM broker (docs/adr/0008).
Q_CLUSTER = {
    "name": "housecairn",
    "orm": "default",
    "workers": env.int("HOUSECAIRN_TASK_WORKERS", default=2),
    "timeout": 300,
    "retry": 360,
    "max_attempts": 3,
    "save_limit": 250,
    "catch_up": False,
    "sync": env.bool("HOUSECAIRN_TASKS_SYNC", default=False),
}

# API tokens (docs/adr/0007).
HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS: int = env.int(
    "HOUSECAIRN_API_TOKEN_DEFAULT_LIFETIME_DAYS", default=90
)
HOUSECAIRN_EVENT_PAYLOAD_MAX_BYTES = 16 * 1024

# Documentation site opened by the help link of each screen (docs/adr/0016).
# A link only: the interface loads nothing from this address.
HOUSECAIRN_DOCS_URL: str = env.str(
    "HOUSECAIRN_DOCS_URL", default="https://docs.housecairn.app"
).rstrip("/")
if urlsplit(HOUSECAIRN_DOCS_URL).scheme not in {"http", "https"}:
    raise ImproperlyConfigured("HOUSECAIRN_DOCS_URL must be an http:// or https:// address.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}
