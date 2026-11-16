"""What differs between two snapshots. Works for any question type through its description."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from django.utils.translation import gettext as _

from app.contracts import JSON, DefinitionRow, QuestionTypePlugin, ScoringStrategyPlugin
from app.domain import banks
from app.domain import settings as app_settings
from app.kernel import registry


@dataclass(frozen=True)
class FieldChange:
    label: str
    locale: str | None
    before: str | None
    after: str | None


@dataclass(frozen=True)
class QuestionChange:
    number: int
    label: str
    rows: list[FieldChange]


@dataclass(frozen=True)
class RevisionDiff:
    quiz_fields: list[FieldChange]
    added: list[QuestionChange]
    removed: list[QuestionChange]
    moved: list[QuestionChange]
    changed: list[QuestionChange]
    draws: list[FieldChange]
    bank_added: list[QuestionChange]
    bank_removed: list[QuestionChange]
    bank_changed: list[QuestionChange]

    @property
    def is_empty(self) -> bool:
        return not (
            self.quiz_fields
            or self.added
            or self.removed
            or self.moved
            or self.changed
            or self.draws
            or self.bank_added
            or self.bank_removed
            or self.bank_changed
        )


def locales_of(snapshot: JSON) -> list[str]:
    """The default language first: plugins describe single values in it."""
    default = snapshot["default_locale"]
    return [default, *(locale for locale in snapshot["locales"] if locale != default)]


def compare(old: JSON | None, new: JSON, locales: Sequence[str]) -> RevisionDiff:
    previous = list(old["questions"]) if old else []
    current = list(new["questions"])
    previous_ids = {question["id"]: question for question in previous}
    current_ids = {question["id"] for question in current}
    added, moved, changed = [], [], []
    common_before = [q["id"] for q in previous if q["id"] in current_ids]
    common_now = [q["id"] for q in current if q["id"] in previous_ids]
    for number, question in enumerate(current, start=1):
        rows = _rows(question, locales)
        before = previous_ids.get(question["id"])
        if before is None:
            added.append(_whole(number, rows, added=True))
            continue
        before_rows = _rows(before, locales)
        difference = _difference(before_rows, rows)
        if difference:
            changed.append(QuestionChange(number, _label(rows, question), difference))
        if common_before.index(question["id"]) != common_now.index(question["id"]):
            moved.append(QuestionChange(number, _label(rows, question), []))
    removed = [
        _whole(number, _rows(question, locales), added=False)
        for number, question in enumerate(previous, start=1)
        if question["id"] not in current_ids
    ]
    bank_added, bank_removed, bank_changed = _pool_changes(old, new, locales)
    return RevisionDiff(
        _quiz_fields(old, new),
        added,
        removed,
        moved,
        changed,
        _draw_changes(old, new),
        bank_added,
        bank_removed,
        bank_changed,
    )


def _draw_text(row: Mapping[str, Any]) -> str:
    text = _("%(count)s questions, %(points)s points each") % {
        "count": row["count"],
        "points": row["points"],
    }
    level = banks.level_label(row.get("difficulty", ""))
    parts = [part for part in (row.get("folder_path"), row.get("tag"), level) if part]
    return ", ".join([text, *parts])


def _draw_changes(old: JSON | None, new: JSON) -> list[FieldChange]:
    before = {row["id"]: row for row in (old or {}).get("draws", [])}
    after = {row["id"]: row for row in new.get("draws", [])}
    changes = []
    for row_id in [*before, *(row_id for row_id in after if row_id not in before)]:
        was, now = before.get(row_id), after.get(row_id)
        label = _("Draw from %(bank)s") % {"bank": (now or was)["bank_name"]}  # type: ignore[index]
        was_text, now_text = _draw_text(was) if was else None, _draw_text(now) if now else None
        if was_text != now_text or (was and now and was["position"] != now["position"]):
            changes.append(FieldChange(label, None, was_text, now_text))
    return changes


def _pool_of(snapshot: JSON | None) -> dict[str, Mapping[str, Any]]:
    rows = (snapshot or {}).get("draws", [])
    return {question["id"]: question for row in rows for question in row.get("pool", [])}


def _pool_changes(
    old: JSON | None, new: JSON, locales: Sequence[str]
) -> tuple[list[QuestionChange], list[QuestionChange], list[QuestionChange]]:
    """Listed once each, even when two rows draw from the same bank."""
    before, after = _pool_of(old), _pool_of(new)
    added = [_whole(0, _rows(q, locales), added=True) for i, q in after.items() if i not in before]
    removed = [
        _whole(0, _rows(q, locales), added=False) for i, q in before.items() if i not in after
    ]
    changed = []
    for question_id, question in after.items():
        if question_id in before:
            rows = _rows(question, locales)
            difference = _difference(_rows(before[question_id], locales), rows)
            if difference:
                changed.append(QuestionChange(0, _label(rows, question), difference))
    return added, removed, changed


def _quiz_fields(old: JSON | None, new: JSON) -> list[FieldChange]:
    fields = []
    old_title: Mapping[str, str] = old["title"] if old else {}
    for locale in sorted({*old_title, *new["title"]}):
        before, after = old_title.get(locale), new["title"].get(locale)
        if before != after:
            fields.append(FieldChange(_("Title"), locale, before, after))
    old_description: Mapping[str, str] = old.get("description", {}) if old else {}
    new_description: Mapping[str, str] = new.get("description", {})
    for locale in sorted({*old_description, *new_description}):
        before, after = old_description.get(locale), new_description.get(locale)
        if before != after:
            fields.append(FieldChange(_("Description"), locale, before, after))
    old_languages = ", ".join(old["locales"]) if old else None
    languages = ", ".join(new["locales"])
    if old_languages != languages:
        fields.append(FieldChange(_("Languages"), None, old_languages, languages))
    old_default = old["default_locale"] if old else None
    if old_default != new["default_locale"]:
        fields.append(FieldChange(_("Default language"), None, old_default, new["default_locale"]))
    return fields


def _scoring_label(question: Mapping[str, Any]) -> str:
    scoring = str(question.get("scoring", ""))
    try:
        strategy = registry.get("scoring_strategy", scoring, include_disabled=True)
    except LookupError:
        return scoring
    return cast(ScoringStrategyPlugin, strategy).label()


def _rows(question: Mapping[str, Any], locales: Sequence[str]) -> list[DefinitionRow]:
    """The stored definition is ours to read even when its module has gone."""
    stored = question.get("settings", {})
    meta = [
        DefinitionRow("meta:points", _("Points"), None, str(stored.get("points", ""))),
        *(
            DefinitionRow(
                f"meta:setting:{key}",
                str(definition.label),
                None,
                str(definition.value_labels.get(stored[key], stored[key])),
            )
            for key, definition in app_settings.CATALOGUE.items()
            if key in stored
        ),
        DefinitionRow("meta:scoring", _("Scoring"), None, _scoring_label(question)),
        DefinitionRow("meta:sources", _("Sources"), None, "\n".join(question.get("sources", []))),
        *(
            DefinitionRow(
                f"meta:explanation:{locale}",
                _("Explanation"),
                locale,
                question.get("explanation", {}).get(locale, ""),
            )
            for locale in locales
        ),
        DefinitionRow(
            "meta:type_version",
            _("Question type version"),
            None,
            str(question.get("type_version", "")),
        ),
    ]
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        rows = list(plugin.describe_definition(question["definition"], locales))
    except LookupError, TypeError, ValueError, AttributeError:
        rows = [
            DefinitionRow("meta:type", _("Question type"), None, question["type"]),
            DefinitionRow(
                "meta:definition",
                _("Definition"),
                None,
                json.dumps(question["definition"], ensure_ascii=False, sort_keys=True),
            ),
        ]
    return rows + meta


def _label(rows: Sequence[DefinitionRow], question: Mapping[str, Any]) -> str:
    return rows[0].value or question.get("type", "")


def _difference(
    before: Sequence[DefinitionRow], after: Sequence[DefinitionRow]
) -> list[FieldChange]:
    old = {(row.key, row.locale): row for row in before}
    new = {(row.key, row.locale): row for row in after}
    changes = []
    for key, row in new.items():
        previous = old.get(key)
        value = previous.value if previous else None
        if value != row.value:
            changes.append(FieldChange(row.label, row.locale, value, row.value))
    changes += [
        FieldChange(row.label, row.locale, row.value, None)
        for key, row in old.items()
        if key not in new
    ]
    return changes


def _whole(number: int, rows: Sequence[DefinitionRow], *, added: bool) -> QuestionChange:
    label = rows[0].value if rows else ""
    return QuestionChange(
        number,
        label,
        [
            FieldChange(
                row.label,
                row.locale,
                None if added else row.value,
                row.value if added else None,
            )
            for row in rows
        ],
    )
