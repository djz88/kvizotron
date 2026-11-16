from decimal import Decimal
from urllib.parse import quote

from django.http import HttpRequest
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext, ngettext
from jinja2 import Environment

from app.domain import clock


def with_lang(request: HttpRequest, code: str) -> str:
    """A language link. A page drawn in answer to a POST has no address to come back to."""
    if request.method != "GET":
        return f"{reverse('admin_quizzes')}?lang={code}"
    query = request.GET.copy()
    query["lang"] = code
    return f"?{query.urlencode()}"


def number(value: Decimal | float | int) -> str:
    """A number as the language writes it, without zeros that say nothing: 50, 12,5, 12.5."""
    text = f"{Decimal(str(value)):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return formats.number_format(Decimal(text), use_l10n=True)


def mailto(address: str) -> str:
    """A `mailto:` link target; the address is quoted so a quoted local part adds no header."""
    return "mailto:" + quote(address, safe="@")


def _admin_basic(request: HttpRequest) -> bool:
    from app.api.admin_view import is_basic  # noqa: PLC0415  # views load after the templates

    return is_basic(request)


def environment(**options: object) -> Environment:
    env = Environment(extensions=["jinja2.ext.i18n"], **options)  # type: ignore[arg-type]  # noqa: S701  # Django's backend turns autoescape on
    env.install_gettext_callables(gettext, ngettext, newstyle=True)  # type: ignore[attr-defined]
    env.globals["url"] = reverse
    env.globals["with_lang"] = with_lang
    env.globals["server_clock"] = clock.server_clock
    env.globals["admin_basic"] = _admin_basic
    env.filters["number"] = number
    env.filters["mailto"] = mailto
    env.filters["when"] = clock.shown
    return env
