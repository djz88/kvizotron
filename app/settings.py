"""Process configuration. Secrets and deployment values come only from the environment."""

import os

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

from app.kernel.discovery import load_modules, load_persistence


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(f"Environment variable {name} must be set")
    return value


def _secret(name: str, minimum: int = 32) -> str:
    value = _required(name)
    if len(value) < minimum:
        raise ImproperlyConfigured(f"{name} must have at least {minimum} characters")
    return value


SECRET_KEY = _secret("KVZ_SECRET_KEY")
_DOMAIN = _required("KVZ_DOMAIN")

DEBUG = os.environ.get("KVZ_DEBUG") == "1"

# "localhost" serves the container health check; Caddy only forwards KVZ_DOMAIN.
ALLOWED_HOSTS = [_DOMAIN, "localhost"]
CSRF_TRUSTED_ORIGINS = [f"https://{_DOMAIN}"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Six months, no subdomains, no preload, as Caddy sends it (AC-132); held here without Caddy too.
SECURE_HSTS_SECONDS = 15552000
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    if not raw.isdecimal() or int(raw) < 1:
        raise ImproperlyConfigured(f"Environment variable {name} must be a positive integer")
    return int(raw)


def _count(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    if not raw.isdecimal():
        raise ImproperlyConfigured(f"Environment variable {name} must be a whole number")
    return int(raw)


# ADR-0030: request limits per client address and minute.
KVZ_LOGIN_ATTEMPTS_PER_MINUTE = _positive_int("KVZ_LOGIN_ATTEMPTS_PER_MINUTE", 5)
KVZ_CODE_ATTEMPTS_PER_MINUTE = _positive_int("KVZ_CODE_ATTEMPTS_PER_MINUTE", 10)
KVZ_SUBMITS_PER_MINUTE = _positive_int("KVZ_SUBMITS_PER_MINUTE", 120)
KVZ_STARTS_PER_MINUTE = _positive_int("KVZ_STARTS_PER_MINUTE", 300)
# Wrong logins from one address across all names; above the per-name limit on purpose.
KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = _positive_int("KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE", 30)
# ADR-0066: proxies in front of the application that append the client address to
# X-Forwarded-For (Caddy in Compose, the ingress in Kubernetes); 0 when it is reached directly.
KVZ_TRUSTED_PROXIES = _count("KVZ_TRUSTED_PROXIES", 1)

# D5: the daily backup of the database and the media, made by the `jobs` service.
KVZ_BACKUP_PATH = os.environ.get("KVZ_BACKUP_PATH", "/data/backups")
KVZ_BACKUP_RETENTION_DAYS = _positive_int("KVZ_BACKUP_RETENTION_DAYS", 30)

KVZ_MODULES = load_modules()
KVZ_PERSISTENCE = load_persistence(KVZ_MODULES)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    # Ahead of django.contrib.auth: the first app wins a management command name.
    *[module.app for module in KVZ_MODULES if "auth" in module.provides],
    "django.contrib.auth",
    "django.contrib.sessions",
    "app.kernel.apps.KernelConfig",
    "app.domain.apps.DomainConfig",
    *[m.app for m in KVZ_MODULES if not {"auth", "theme"} & set(m.provides)],
    # Templates are searched in this order, so a theme can replace any page of app.api.
    *[module.app for module in KVZ_MODULES if "theme" in module.provides],
    "app.api.apps.ApiConfig",
]
AUTH_USER_MODEL = "kernel.AdminUser"
AUTHENTICATION_BACKENDS = [m.auth_backend for m in KVZ_MODULES if "auth" in m.provides]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
# CommonMiddleware is what validates the Host header against ALLOWED_HOSTS.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    # Before anything that reads the body, after the two that add headers to every answer, so a
    # refusal carries them too (ADR-0066).
    "app.kernel.middleware.BodyLimitMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Ahead of everything that reads the form: reading it spools the upload.
    "app.kernel.middleware.RefuseMultipartMiddleware",
    "app.api.i18n.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "app.kernel.middleware.ModuleGateMiddleware",
    "app.api.run_clock.RunClockMiddleware",
    # Last: it must not run before the work of the others, and a failure in it changes nothing.
    "app.api.heartbeat.HeartbeatMiddleware",
]
# data: only for images, which Pico CSS uses for its icons. https: for images a quiz loads from
# their own server (ADR-0043).
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:", "https:"],
    # The nonce is added only to a page that asks for it: the block of custom colours (ADR-0054).
    "style-src": [CSP.SELF, CSP.NONCE],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}
KVZ_MEDIA_PATH = os.environ.get("KVZ_MEDIA_PATH", "/data/media")
# An upload stays in memory up to Caddy's body limit, so no temporary files stay behind.
FILE_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
ROOT_URLCONF = "app.urls"
WSGI_APPLICATION = "app.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "APP_DIRS": True,
        "OPTIONS": {"environment": "app.api.jinja.environment"},
    }
]
USE_TZ = True
# Django would otherwise set the process zone to its default, America/Chicago. Quiz times use the
# zone chosen in the global settings; this is only the zone the server runs in (`TZ`).
TIME_ZONE = os.environ.get("TZ") or "UTC"
USE_I18N = True
LANGUAGE_CODE = "cs"
LANGUAGES = [("cs", "Čeština"), ("en", "English"), ("uk", "Українська")]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Paths and tracebacks only: Django does not log request bodies, so no answers reach the log.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "app": {"handlers": ["console"], "level": "WARNING"},
    },
}

DATABASES = {"default": KVZ_PERSISTENCE.database_settings()}
