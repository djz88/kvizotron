from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext, ngettext
from jinja2 import Environment


def with_lang(request: HttpRequest, code: str) -> str:
    """A language link. A page drawn in answer to a POST has no address to come back to."""
    if request.method != "GET":
        return f"{reverse('admin_quizzes')}?lang={code}"
    query = request.GET.copy()
    query["lang"] = code
    return f"?{query.urlencode()}"


def environment(**options: object) -> Environment:
    env = Environment(extensions=["jinja2.ext.i18n"], **options)  # type: ignore[arg-type]  # noqa: S701  # Django's backend turns autoescape on
    env.install_gettext_callables(gettext, ngettext, newstyle=True)  # type: ignore[attr-defined]
    env.globals["url"] = reverse
    env.globals["with_lang"] = with_lang
    return env
