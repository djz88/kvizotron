"""Choosing the language of a request (FR-03, FR-04). Texts live in Django gettext catalogues."""

from collections.abc import Sequence

from django.http import HttpRequest
from django.utils import translation
from django.utils.translation.trans_real import parse_accept_lang_header

PUBLIC_LOCALES = ("cs", "en", "uk")
ADMIN_LOCALES = ("cs", "en")
DEFAULT_LOCALE = "cs"
ADMIN_SESSION_KEY = "admin_lang"


def negotiate(request: HttpRequest, allowed: Sequence[str], default: str) -> str:
    """The form or query choice, then Accept-Language, each limited to `allowed`."""
    chosen = request.POST.get("lang") or request.GET.get("lang")
    return chosen if chosen in allowed else _from_header(request, allowed, default)


def _from_header(request: HttpRequest, allowed: Sequence[str], default: str) -> str:
    header = request.headers.get("Accept-Language", "")
    for code, _quality in parse_accept_lang_header(header):
        base = code.split("-")[0].lower()
        if base in allowed:
            return base
    return default


def _for_admin(request: HttpRequest) -> str:
    session = getattr(request, "session", None)
    chosen = request.GET.get("lang")
    if chosen in ADMIN_LOCALES:
        if session is not None:
            session[ADMIN_SESSION_KEY] = chosen
        return chosen
    if session is not None and session.get(ADMIN_SESSION_KEY) in ADMIN_LOCALES:
        return session[ADMIN_SESSION_KEY]
    return _from_header(request, ADMIN_LOCALES, DEFAULT_LOCALE)


class LocaleMiddleware:
    """Activates a language for one request. A thread must not carry it to the next one."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            locale = _for_admin(request)
        else:
            # Only the query and the header: reading a form body here would defeat upload limits.
            locale = _public_locale(request)
        translation.activate(locale)
        request.locale = locale
        try:
            return self.get_response(request)
        finally:
            translation.deactivate()


def _public_locale(request: HttpRequest) -> str:
    chosen = request.GET.get("lang")
    if chosen in PUBLIC_LOCALES:
        return chosen
    return _from_header(request, PUBLIC_LOCALES, DEFAULT_LOCALE)
