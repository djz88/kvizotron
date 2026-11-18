"""What every page needs: language, theme and the question markup."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.context_processors import csp
from django.urls import NoReverseMatch, reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from markupsafe import Markup

from app.contracts import (
    ASK_EMAIL,
    ASK_NAME,
    ASK_WHEN,
    IMAGE_MODE_EXTERNAL,
    JSON,
    PHOTO_VISIBILITY,
    ImporterProvider,
    MediaStorageProvider,
    QuestionTypePlugin,
    QuizFlowPlugin,
    ThemePlugin,
)
from app.domain import branding, participants, settings, tokens
from app.domain.models import Attempt, Quiz, QuizRun
from app.kernel import registry
from app.kernel.lifecycle import Blocker

ASSETS = Path(__file__).parent / "assets"


@cache
def _digest(path: Path, modified: int, size: int) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def versioned(address: str, path: Path) -> str:
    """`address?v=<fingerprint>`: files are served with `max-age`, so without the content in the
    address a browser keeps an old copy that long after a deploy. Read again when the file changes.
    """
    found = path.stat()
    return f"{address}?v={_digest(path, found.st_mtime_ns, found.st_size)}"


SOURCE_LINK = re.compile(r"https://\S+")
SCRIPTS = (
    "htmx.min.js",
    "play.js",
    "flow.js",
    "resume.js",
    "nav.js",
    "sections.js",
    "sortable.js",
    "editor.js",
    "clock.js",
    "countdown.js",
    "planned.js",
    "number.js",
    "inline-edit.js",
)
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


def last_theme_usage(module_id: str) -> list[Blocker]:
    """A page cannot be drawn without a theme."""
    owned = registry.owned_by(module_id)
    themes = [("theme", key) for key in registry.keys("theme")]
    if any(theme in owned for theme in themes) and all(theme in owned for theme in themes):
        return [Blocker("in_use", _("it is the last enabled theme"))]
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
            **csp(request),  # the nonce of the colours block; read only by a page that has one
            "theme": current_theme(),
            "locale": locale,
            "htmx_config": HTMX_CONFIG,
            "scripts": [versioned(reverse("asset", args=[n]), ASSETS / n) for n in SCRIPTS],
            # Only public pages of a quiz pass `branding_quiz`; the rest use the global branding.
            "app_version": APP_VERSION,
            "footer_year": datetime.now(settings.zone()).year,
            "footer_badges": footer_badges(),
            "branding": branding.resolve(context.get("branding_quiz"), locale),
        },
        status=status,
    )


try:
    APP_VERSION = version("kvizotron")
except PackageNotFoundError:  # not installed as a distribution
    APP_VERSION = ""
BADGES = ("python", "django", "htmx")


def footer_badges() -> list[tuple[str, str]]:
    """(technology, URL) of the footer badges, which the theme serves."""
    names = {"python": "Python", "django": "Django", "htmx": "HTMX"}
    return [(names[b], reverse("theme.default:asset", args=[f"badge-{b}.svg"])) for b in BADGES]


def importer() -> ImporterProvider | None:
    """None when the module is not there, like `media_storage`."""
    try:
        return cast(ImporterProvider, registry.get("importer", "csv"))
    except LookupError:
        return None


def can_import() -> bool:
    return importer() is not None


def mode_bar_of(run: QuizRun) -> dict[str, Any] | None:
    """A tester must know that the result counts for nothing."""
    if run.kind != QuizRun.Kind.TEST:
        return None
    return {"text": gettext_lazy("This is a test. The result does not count."), "links": []}


def media_storage() -> MediaStorageProvider | None:
    keys = registry.keys("media_storage")
    return cast(MediaStorageProvider, registry.get("media_storage", keys[0])) if keys else None


def with_media_urls(value: Any, keep_asset: bool = False, external: bool = False) -> Any:
    """Plugins know asset ids and the API knows routes. An editor still needs the id itself.

    An image with no copy can only load from its address. Unless kept for an editor, neither the id
    nor the address stays, so a copy's address cannot reach a page by accident.
    """
    if isinstance(value, Mapping):
        resolved = {key: with_media_urls(item, keep_asset, external) for key, item in value.items()}
        asset, source = resolved.get("asset"), resolved.get("source")
        if source and (external or not asset):
            resolved["url"] = source
        elif asset:
            try:
                resolved["url"] = reverse("media", args=[asset])
            except NoReverseMatch:
                resolved["url"] = ""
        if not keep_asset:
            resolved.pop("asset", None)
            resolved.pop("source", None)
        return resolved
    if isinstance(value, list):
        return [with_media_urls(item, keep_asset, external) for item in value]
    return value


def shows_external_images(quiz: Quiz, question: Mapping[str, Any]) -> bool:
    return settings.image_mode(quiz, question) == IMAGE_MODE_EXTERNAL


def question_settings(quiz: Quiz, question: Mapping[str, Any]) -> dict[str, Any]:
    """Values a question type may need to draw itself; a plugin reads no settings."""
    values = {
        settings.NONE_OPTION: settings.resolve(settings.NONE_OPTION, quiz, question),
        "external_images": shows_external_images(quiz, question),
    }
    if PHOTO_VISIBILITY in settings.CATALOGUE:
        values[PHOTO_VISIBILITY] = settings.resolve(PHOTO_VISIBILITY, quiz, question)
    return values


def delete_images(asset_ids: Sequence[str]) -> None:
    """After the transaction that forgot them, so a failure leaves a file and never a hole."""
    storage = media_storage()
    if storage is not None:
        for asset_id in asset_ids:
            storage.delete_image(asset_id)


ONE_PAGE = {"step": False, "back": False, "check": False, "page": 1}
FLOW_MODULE = "flow.basic"


def flow_options(flow: Mapping[str, Any]) -> JSON:
    """Without the module, or with a mode it does not know, the one-page form still works."""
    try:
        plugin = cast(QuizFlowPlugin, registry.get("quiz_flow", FLOW_MODULE, include_disabled=True))
    except LookupError:
        return ONE_PAGE
    if flow["navigation"] not in plugin.modes():
        return ONE_PAGE
    options = dict(plugin.client_options(flow["navigation"], flow["moment"]))
    # The size is fixed on the attempt; an attempt from before pages has none (ADR-0052).
    options["page"] = int(flow.get("page_size") or 1) if options.get("pages") else 1
    return options


def question_label(question: Mapping[str, Any], locale: str) -> str:
    """Plugins may not agree on a prompt field; the type id is the fallback."""
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        payload = plugin.public_payload(question["definition"], locale)
    except LookupError, TypeError, ValueError, AttributeError:
        return question["type"]
    return payload.get("prompt") or question["type"]


def result_sources(
    questions: Sequence[Mapping[str, Any]], sources: str, locale: str
) -> list[dict[str, Any]]:
    """Only a whole `https://` address becomes a link; anything else stays text.

    `sources` is the quiz-level value (the run's in play, the quiz's in preview); a question's wins.
    """
    return [
        {
            "question": question_label(question, locale),
            "lines": [
                {"text": line, "is_link": bool(SOURCE_LINK.fullmatch(line))}
                for line in question["sources"]
            ],
        }
        for question in questions
        if question.get("sources")
        and (settings.question_value(settings.SHOW_SOURCES, question) or sources)
        == settings.ShowSources.ON
    ]


def reveal_context(
    question: Mapping[str, Any],
    revealed: Any,
    answer: JSON | None,
    locale: str,
    with_prompt: bool,
    quiz: Quiz,
) -> dict[str, Any]:
    """Plain values for `public/_reveal.html`. Only here does a correct answer reach a page."""
    solution = None
    if revealed.show_answers:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        with translation.override(locale):
            definition = with_media_urls(
                question["definition"], external=shows_external_images(quiz, question)
            )
            html = plugin.render_solution(definition, locale, answer)
        solution = Markup(html)  # noqa: S704  # the plugin escapes through its own template
    return {
        "prompt": question_label(question, locale) if with_prompt else None,
        "state": revealed.state.value,
        "earned": revealed.earned,
        "maximum": revealed.maximum,
        "solution_html": solution,
        "explanation": revealed.explanation,
    }


def question_html(
    question: Mapping[str, Any],
    locale: str,
    quiz_settings: JSON,
    answer: JSON | None = None,
    changed: bool = False,
    option_seed: str | None = None,
) -> Markup:
    """The domain adds the id, so a plugin can name its inputs `<id>:<field>`."""
    plugin = cast(
        QuestionTypePlugin,
        registry.get("question_type", question["type"], include_disabled=True),
    )
    if option_seed:
        quiz_settings = {**quiz_settings, "shuffle_seed": f"{option_seed}:{question['id']}"}
    payload = plugin.public_payload(question["definition"], locale, quiz_settings)
    public = with_media_urls(
        {**payload, "id": question["id"]}, external=bool(quiz_settings.get("external_images"))
    )
    with translation.override(locale):  # the page activates the language only later
        html = Markup(plugin.render_public(public, locale, answer))  # noqa: S704  # the plugin escapes through its own Jinja2 template
        if not changed:
            return html
        mark = Markup(
            '<div class="question-changed"><p role="note"><strong>{}</strong></p>{}</div>'
        )
        return mark.format(_("This question changed"), html)


def identity_context(
    rules: Mapping[str, str], name: str = "", email: str = "", refused: bool = False
) -> dict[str, Any] | None:
    """What the name and e-mail fields need. None when the run asks for neither."""
    name_mode, email_mode = rules.get(ASK_NAME, "off"), rules.get(ASK_EMAIL, "off")
    if name_mode == "off" and email_mode == "off":
        return None
    return {
        "name": name_mode,
        "email": email_mode,
        "when": rules.get(ASK_WHEN, "end"),
        "name_value": name if name_mode != "off" else "",
        "email_value": email if email_mode != "off" else "",
        "refused": refused,
    }


def identity_form(attempt: Attempt) -> dict[str, Any] | None:
    """The form on a result for what is still missing, until the run is archived."""
    gap = participants.missing(attempt.participant)
    if not gap or attempt.run.status == QuizRun.Status.ARCHIVED:
        return None
    rules = participants.rules_of(attempt.run)
    form = identity_context(
        rules
        | {ASK_NAME: rules[ASK_NAME] if gap.name else "off"}
        | {ASK_EMAIL: rules[ASK_EMAIL] if gap.email else "off"}
    )
    if form is None:
        return None
    return form | {"action": reverse("result_identity", args=[tokens.issue_result(attempt.id)])}
