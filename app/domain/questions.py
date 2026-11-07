"""What every stored question has, whether it lives in a quiz or in a bank."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from app.contracts import JSON, QuestionTypePlugin
from app.domain import settings
from app.kernel import registry

DEFAULT_POINTS = 1
MAX_SOURCES = 10
MAX_SOURCE_LENGTH = 300


def apply_fields(
    question: dict[str, Any],
    plugin: QuestionTypePlugin,
    config: JSON,
    *,
    points: int | None = None,
    scoring: str | None = None,
    sources: Sequence[str] | None = None,
    explanation: Mapping[str, str] | None = None,
    setting_values: Mapping[str, str] | None = None,
) -> None:
    """What is left out stays as it was."""
    question.update(type=plugin.id, type_version=plugin.version, definition=dict(config))
    if points is not None:
        question["settings"] = {**question["settings"], "points": points}
    if scoring is not None:
        question["scoring"] = scoring
    if sources is not None:
        question["sources"] = list(sources)
    if explanation is not None:
        question["explanation"] = dict(explanation)
    if setting_values is not None:
        kept = {k: v for k, v in question["settings"].items() if k not in settings.CATALOGUE}
        question["settings"] = {**kept, **setting_values}


def is_blank(answer: JSON | None) -> bool:
    """A form sends a select left on its placeholder as an empty value."""
    if not answer:
        return True
    return not any(answer.values())


def images_of(definition: Any) -> list[Mapping[str, Any]]:
    """Plugins are opaque, so this finds images by their shape, as `with_media_urls` does."""
    if isinstance(definition, Mapping):
        found = [definition] if "alt" in definition and _is_image(definition) else []
        return found + [image for item in definition.values() for image in images_of(item)]
    if isinstance(definition, list):
        return [image for item in definition for image in images_of(item)]
    return []


def _is_image(value: Mapping[str, Any]) -> bool:
    return "asset" in value or "source" in value


def has_image_without_copy(question: Mapping[str, Any]) -> bool:
    return any(not image.get("asset") for image in images_of(question["definition"]))


def explanation_gaps(question: Mapping[str, Any], locales: Sequence[str]) -> list[str]:
    """An explanation is optional, but one that exists must exist in every listed language."""
    explanation = question.get("explanation") or {}
    filled = [locale for locale in locales if explanation.get(locale)]
    return [locale for locale in locales if locale not in filled] if filled else []


def explanation_covers(question: Mapping[str, Any], locales: Sequence[str]) -> bool:
    """No explanation at all, or one in each listed language, wherever else it may exist."""
    explanation = question.get("explanation") or {}
    filled = {locale for locale, text in explanation.items() if text}
    return not filled or filled.issuperset(locales)


def complete_locales(question: Mapping[str, Any], locales: Sequence[str]) -> list[str]:
    to_fix = locales_to_fix(question, locales)
    return [locale for locale in locales if locale not in to_fix]


def locales_to_fix(question: Mapping[str, Any], locales: Sequence[str]) -> list[str]:
    """Languages the question cannot be published in; an unavailable type is a separate problem."""
    try:
        plugin = cast(QuestionTypePlugin, registry.get("question_type", question["type"]))
    except LookupError:
        return []
    gaps = set(explanation_gaps(question, locales))
    to_fix = []
    for locale in locales:
        try:
            plugin.validate_definition(question["definition"], locale)
        except ValueError:
            to_fix.append(locale)
        else:
            if locale in gaps:
                to_fix.append(locale)
    return to_fix
