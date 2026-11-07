"""What a download holds: the same columns an import reads (ADR-0045). Draw rows stay out."""

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.contracts import QuestionTypePlugin
from app.domain import authoring, question_import, questions, settings
from app.domain.models import QuestionBank, Quiz
from app.kernel import audit, registry

FIRST_COLUMNS = ["schema_version", "row_type", "type", "slug", "locales", "default_locale"]


@dataclass(frozen=True)
class ExportData:
    columns: list[str]
    rows: list[dict[str, str]]
    assets: dict[str, str]  # file name in the archive -> asset id
    omitted_draws: bool


def _default_name(asset_id: str) -> str:
    return f"images/{asset_id}"


def _common(question: Mapping[str, Any], locales: Sequence[str]) -> dict[str, str]:
    stored = question.get("settings") or {}
    explanation = question.get("explanation") or {}
    cells = {
        "schema_version": question_import.SCHEMA_VERSION,
        "row_type": question_import.QUESTION_ROW,
        "type": str(question["type"]),
        "scoring": str(question["scoring"]),
        "sources": "\n".join(question.get("sources") or []),
    }
    cells |= {
        f"explanation_{locale}": str(explanation[locale])
        for locale in locales
        if explanation.get(locale)
    }
    cells |= {
        f"{question_import.SETTING_PREFIX}{key}": str(value)
        for key, value in stored.items()
        if key in settings.CATALOGUE
    }
    return cells


def _question_row(
    question: Mapping[str, Any],
    locales: Sequence[str],
    assets: dict[str, str],
    name_of: Callable[[str], str],
) -> dict[str, str]:
    """On a copy: a file name goes where `to_csv` looks, and never into what is stored."""
    definition = copy.deepcopy(question["definition"])
    for found in questions.images_of(definition):
        image = cast(dict[str, Any], found)
        asset = image.get("asset")
        if asset and not image.get("source"):
            name = name_of(str(asset))
            assets[name] = str(asset)
            image["source"] = name
    plugin = cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )
    return _common(question, locales) | dict(plugin.to_csv(definition, locales))


def _columns(rows: Sequence[Mapping[str, str]]) -> list[str]:
    found = dict.fromkeys(FIRST_COLUMNS)
    for row in rows:
        found |= dict.fromkeys(row)
    return list(found)


def _quiz_row(quiz: Quiz) -> dict[str, str]:
    cells = {
        "schema_version": question_import.SCHEMA_VERSION,
        "row_type": question_import.QUIZ_ROW,
        "slug": quiz.slug,
        "locales": ",".join(quiz.supported_locales),
        "default_locale": quiz.default_locale,
    }
    cells |= {f"title_{locale}": str(text) for locale, text in quiz.title.items()}
    cells |= {f"description_{locale}": str(text) for locale, text in quiz.description.items()}
    for key in settings.keys_for("quiz"):
        value = settings.quiz_override(key, quiz)
        if value is not None:
            cells[f"{question_import.SETTING_PREFIX}{key}"] = str(value)
    return cells


def rows_for_quiz(quiz: Quiz, name_of: Callable[[str], str] = _default_name) -> ExportData:
    """The draft if there is one, otherwise the current published revision."""
    assets: dict[str, str] = {}
    rows = [_quiz_row(quiz)]
    for question in authoring.editable_questions(quiz):
        row = _question_row(question, quiz.supported_locales, assets, name_of)
        points = (question.get("settings") or {}).get("points")
        if points is not None:
            row["points"] = str(points)
        rows.append(row)
    return ExportData(_columns(rows), rows, assets, bool(authoring.editable_draws(quiz)))


def rows_for_bank(bank: QuestionBank, name_of: Callable[[str], str] = _default_name) -> ExportData:
    """Points belong to a draw row, not to a bank question."""
    assets: dict[str, str] = {}
    rows = []
    locales = question_import.languages()
    for stored in bank.questions.order_by("created_at"):
        row = _question_row(stored.question_json, locales, assets, name_of)
        row["tags"] = ",".join(stored.tags)
        rows.append(row)
    return ExportData(_columns(rows), rows, assets, False)


def record_download(entity_type: str, entity_id: Any, admin_id: str, rows: int) -> None:
    """A download holds the answer keys, so it is worth a trace."""
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="export.downloaded",
        entity_type=entity_type,
        entity_id=str(entity_id),
        details={"rows": rows},
    )
