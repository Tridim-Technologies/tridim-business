import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _positive_int_setting(name, default):
    try:
        value = int(os.environ.get(name, default))
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from error
    if value < 1:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=0")
    SECRET_KEY = secrets.token_urlsafe(48)

ALLOWED_HOSTS = [
    host
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host
]
CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "customers",
    "quotations",
    "invoicing",
    "health",
    "hr",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Invitation email is optional. The console backend remains the safe local
# default; enable SMTP only after configuring credentials through the runtime
# environment. A sent invitation link points to the frontend origin and is
# placed in a URL fragment so it is not sent in the initial HTTP request.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = _positive_int_setting("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "0") == "1"
EMAIL_TIMEOUT = _positive_int_setting("EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "Tridim Business <no-reply@example.invalid>"
)
INVITATION_EMAIL_ENABLED = os.environ.get("INVITATION_EMAIL_ENABLED", "0") == "1"
INVITATION_BASE_URL = os.environ.get("INVITATION_BASE_URL", "").strip()
if INVITATION_EMAIL_ENABLED:
    if EMAIL_USE_TLS and EMAIL_USE_SSL:
        raise ImproperlyConfigured("Enable only one of EMAIL_USE_TLS or EMAIL_USE_SSL.")
    if EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend" and not (
        DEBUG and EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"
    ):
        raise ImproperlyConfigured(
            "Invitation email requires Django's SMTP backend outside tests."
        )
    if not EMAIL_HOST or "example.invalid" in DEFAULT_FROM_EMAIL:
        raise ImproperlyConfigured(
            "Invitation email requires EMAIL_HOST and a real DEFAULT_FROM_EMAIL."
        )
    parsed_invitation_url = urlsplit(INVITATION_BASE_URL)
    if (
        not parsed_invitation_url.netloc
        or parsed_invitation_url.scheme not in {"http", "https"}
        or parsed_invitation_url.username
        or parsed_invitation_url.password
        or parsed_invitation_url.query
        or parsed_invitation_url.fragment
        or (not DEBUG and parsed_invitation_url.scheme != "https")
    ):
        raise ImproperlyConfigured(
            "INVITATION_BASE_URL must be an origin/path URL; use HTTPS outside local development."
        )

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

DARAJA_ENV = os.environ.get("DARAJA_ENV", "sandbox").strip().lower()
if DARAJA_ENV != "sandbox":
    raise ImproperlyConfigured("This release supports Daraja sandbox mode only.")
DARAJA_CONSUMER_KEY = os.environ.get("DARAJA_CONSUMER_KEY", "")
DARAJA_CONSUMER_SECRET = os.environ.get("DARAJA_CONSUMER_SECRET", "")
DARAJA_SHORTCODE = os.environ.get("DARAJA_SHORTCODE", "")
DARAJA_PASSKEY = os.environ.get("DARAJA_PASSKEY", "")
DARAJA_CALLBACK_URL = os.environ.get("DARAJA_CALLBACK_URL", "")

# Expense evidence is a gated synthetic-data feature. Never enable it in an
# environment that accepts real evidence until its storage, scanner, retention,
# backup, support, and incident controls have been reviewed.
EXPENSE_EVIDENCE_ENABLED = (
    DEBUG
    and bool(ALLOWED_HOSTS)
    and all(host in {"localhost", "127.0.0.1", "[::1]"} for host in ALLOWED_HOSTS)
    and os.environ.get("EXPENSE_EVIDENCE_ENABLED", "0") == "1"
)
EXPENSE_EVIDENCE_LOCAL_HOSTS_ALLOWED = bool(ALLOWED_HOSTS) and all(
    host in {"localhost", "127.0.0.1", "[::1]"} for host in ALLOWED_HOSTS
)
EXPENSE_EVIDENCE_STORAGE_ROOT = Path(
    os.environ.get("EXPENSE_EVIDENCE_STORAGE_ROOT") or BASE_DIR / ".private-evidence"
)
EXPENSE_EVIDENCE_LEDGER_ROOT = Path(
    os.environ.get("EXPENSE_EVIDENCE_LEDGER_ROOT")
    or BASE_DIR / ".private-evidence-ledger"
)
EXPENSE_EVIDENCE_CLAMD_SOCKET = os.environ.get("EXPENSE_EVIDENCE_CLAMD_SOCKET", "")
EXPENSE_EVIDENCE_MAX_FILE_BYTES = _positive_int_setting(
    "EXPENSE_EVIDENCE_MAX_FILE_BYTES", 10 * 1024 * 1024
)
EXPENSE_EVIDENCE_MAX_FILES_PER_VERSION = _positive_int_setting(
    "EXPENSE_EVIDENCE_MAX_FILES_PER_VERSION", 5
)
EXPENSE_EVIDENCE_MAX_TOTAL_BYTES = _positive_int_setting(
    "EXPENSE_EVIDENCE_MAX_TOTAL_BYTES", 25 * 1024 * 1024
)
EXPENSE_EVIDENCE_QUARANTINE_SECONDS = _positive_int_setting(
    "EXPENSE_EVIDENCE_QUARANTINE_SECONDS", 3600
)
DATA_UPLOAD_MAX_MEMORY_SIZE = 26 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024

LOGIN_MAX_REQUEST_BYTES = _positive_int_setting("LOGIN_MAX_REQUEST_BYTES", 4096)
LOGIN_ATTEMPTS_PER_IDENTITY_IP = _positive_int_setting(
    "LOGIN_ATTEMPTS_PER_IDENTITY_IP", 10
)
LOGIN_ATTEMPTS_PER_IP = _positive_int_setting("LOGIN_ATTEMPTS_PER_IP", 300)
LOGIN_ATTEMPT_WINDOW_SECONDS = _positive_int_setting(
    "LOGIN_ATTEMPT_WINDOW_SECONDS", 900
)
DARAJA_CALLBACK_MAX_BODY_BYTES = _positive_int_setting(
    "DARAJA_CALLBACK_MAX_BODY_BYTES", 16384
)
DARAJA_CALLBACK_REQUESTS_PER_IP = _positive_int_setting(
    "DARAJA_CALLBACK_REQUESTS_PER_IP", 600
)
DARAJA_CALLBACK_RATE_WINDOW_SECONDS = _positive_int_setting(
    "DARAJA_CALLBACK_RATE_WINDOW_SECONDS", 60
)
DARAJA_UNKNOWN_CALLBACKS_PER_MINUTE = _positive_int_setting(
    "DARAJA_UNKNOWN_CALLBACKS_PER_MINUTE", 300
)
DARAJA_UNKNOWN_CALLBACK_RATE_WINDOW_SECONDS = _positive_int_setting(
    "DARAJA_UNKNOWN_CALLBACK_RATE_WINDOW_SECONDS", 60
)
DARAJA_UNKNOWN_CALLBACK_RETENTION_SECONDS = _positive_int_setting(
    "DARAJA_UNKNOWN_CALLBACK_RETENTION_SECONDS", 300
)
ENDPOINT_RATE_LIMIT_BUCKET_RETENTION_SECONDS = _positive_int_setting(
    "ENDPOINT_RATE_LIMIT_BUCKET_RETENTION_SECONDS", 86400
)
