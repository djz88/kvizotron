"""What every page needs: language, theme and the question markup."""

import json
from collections.abc import Mapping
from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import translation
from markupsafe import Markup

from app.contracts import QuestionTypePlugin, ThemePlugin
from app.kernel import registry

# Eval and injected styles are off because of the CSP. 4xx responses carry a message to show.
HTMX_CONFIG = json.dumps(
    {
        "allowEval": False,
        "allowScriptTags": False,
        "includeIndicatorStyles": False,
        "historyCacheSize": 0,
        "responseHandling": [
            {"code": "204", "swap": False},
            {"code": "[23]..", "swap": True},
            {"code": "4..", "swap": True},
            {"code": "5..", "swap": False, "error": True},
        ],
    }
)


def current_theme() -> ThemePlugin:
    return cast(ThemePlugin, registry.get("theme", registry.keys("theme")[0]))


def last_theme_usage(module_id: str) -> list[str]:
    """A page cannot be drawn without a theme."""
    owned = registry.owned_by(module_id)
    themes = [("theme", key) for key in registry.keys("theme")]
    if any(theme in owned for theme in themes) and all(theme in owned for theme in themes):
        return ["it is the last enabled theme"]
    return []


def page(
    request: HttpRequest, template: str, context: dict[str, Any], locale: str, status: int = 200
) -> HttpResponse:
    translation.activate(locale)
    return render(
        request,
        template,
        {
            **context,
            "theme": current_theme(),
            "locale": locale,
            "htmx_config": HTMX_CONFIG,
            "scripts": [reverse("asset", args=[n]) for n in ("htmx.min.js", "play.js")],
        },
        status=status,
    )


def question_html(question: Mapping[str, Any], locale: str) -> Markup:
    """The domain adds the id, so a plugin can name its inputs `<id>:<field>`."""
    plugin = cast(
        QuestionTypePlugin,
        registry.get("question_type", question["type"], include_disabled=True),
    )
    payload = plugin.public_payload(question["definition"], locale)
    return Markup(plugin.render_public({**payload, "id": question["id"]}, locale))  # noqa: S704  # the plugin escapes through its own Jinja2 template
