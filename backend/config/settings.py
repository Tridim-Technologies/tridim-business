import os
import secrets
from pathlib import Path

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
