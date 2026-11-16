"""Applying a quiz type: its values become quiz overrides and the quiz remembers it (ADR-0062).

The types come from the `quiz_type` port; the rules for applying them live here. A key of a disabled
module is skipped, a clash with another setting is adjusted (`setting_rules.ADJUSTABLE`) and any
other clash refuses the type. Content a type does not go with only warns.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from django.conf import settings as django_settings
from django.db import transaction

from app.contracts import QuizTypePlugin
from app.domain import authoring, requirements, settings
from app.domain.models import AppSetting, Quiz, QuizRun
from app.domain.setting_rules import ADJUSTABLE, Clash, clashes
from app.kernel import audit, registry
from app.kernel.registry import ModuleDisabled, UnknownPort

QUIZ_TYPE = "quiz_type"
_LIVE = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN)


class TypeRefused(Exception):
    """Raised for any clash that cannot be adjusted, including one with a planned or open run.

    Nothing was written.
    """

    def __init__(self, clashes: list[Clash]) -> None:
        super().__init__(", ".join(clash.reason for clash in clashes))
        self.clashes = list(clashes)


class UnknownType(Exception):
    """Not registered, or its module is disabled."""


@dataclass(frozen=True)
class Change:
    key: str
    current: str  # the value the quiz resolves to now
    new: str | None  # None: back to the global value


@dataclass(frozen=True)
class Preview:
    type_id: str
    # Values the type writes, only where they differ; removals whenever the quiz has an override
    # for the key.
    changes: list[Change]
    adjusted: list[Change]  # clash fixes on other settings
    skipped: list[str]  # keys of disabled modules
    refused: list[Clash]  # non-adjustable clashes; non-empty = cannot apply
    live_run: bool  # a planned or open run exists
    content: list[str]  # requirement keys the quiz content does not meet


def available() -> list[QuizTypePlugin]:
    """Types of enabled modules, in their order."""
    found = [
        cast(QuizTypePlugin, registry.get(QUIZ_TYPE, key, include_disabled=True))
        for key in registry.keys(QUIZ_TYPE)
    ]
    return sorted(found, key=lambda item: item.order)


def get(type_id: str) -> QuizTypePlugin | None:
    """A disabled module's type too, so a quiz can still name the type it remembers."""
    try:
        return cast(QuizTypePlugin, registry.get(QUIZ_TYPE, type_id, include_disabled=True))
    except UnknownPort:
        return None


def _enabled(type_id: str) -> QuizTypePlugin:
    try:
        return cast(QuizTypePlugin, registry.get(QUIZ_TYPE, type_id))
    except (UnknownPort, ModuleDisabled) as exc:
        raise UnknownType(type_id) from exc


def _skips() -> Callable[[str], bool]:
    """Whether a key is left alone: no longer known, or owned by a disabled module.

    A core key has no owning module and is never skipped.
    """
    owners = {
        declared.key: module.id
        for module in django_settings.KVZ_MODULES
        for declared in module.settings
    }
    states: dict[str, bool] = {}

    def skipped(key: str) -> bool:
        if key not in settings.CATALOGUE:
            return True
        owner = owners.get(key)
        if owner is None:
            return False
        if owner not in states:
            states[owner] = registry.is_enabled(owner)
        return not states[owner]

    return skipped


def _rows(quiz: Quiz) -> dict[str, str]:
    """The quiz's stored overrides of known keys, even a value a release no longer offers."""
    stored = AppSetting.objects.filter(quiz=quiz).values_list("key", "value_json")
    return {key: value for key, value in stored if key in settings.CATALOGUE}


def _removed_by_change(quiz: Quiz, new: QuizTypePlugin) -> list[str]:
    """The keys the old type sets and the new one does not, by the old type's current definition."""
    if not quiz.quiz_type or quiz.quiz_type == new.id:
        return []
    old = get(quiz.quiz_type)
    if old is None or old.resets_all:
        return []
    return [key for key in old.values() if key not in new.values()]


def _plan(quiz: Quiz, type_id: str) -> tuple[Preview, dict[str, str | None]]:
    """The preview and the overrides to write (`None` deletes one), from the current state."""
    new = _enabled(type_id)
    skipped = _skips()
    rows = _rows(quiz)
    globals_ = {key: settings.resolve(key) for key in settings.CATALOGUE}
    current = {
        key: value
        for key, value in rows.items()
        if value in settings.CATALOGUE[key].choices  # as `settings.quiz_override` reads it
    }
    now = {key: current.get(key, globals_[key]) for key in settings.CATALOGUE}

    left_alone: list[str] = []
    removals: list[str] = []
    candidates = sorted(rows) if new.resets_all else _removed_by_change(quiz, new)
    for key in candidates:
        if key not in rows:
            continue
        if skipped(key):
            left_alone.append(key)
        else:
            removals.append(key)
    sets: dict[str, str] = {}
    for key, value in new.values().items():
        if skipped(key):
            left_alone.append(key)
        else:
            sets[key] = value

    target = {key: value for key, value in current.items() if key not in removals} | sets

    def resolved() -> dict[str, str]:
        return {key: target.get(key, globals_[key]) for key in settings.CATALOGUE}

    found = clashes(resolved(), quiz)
    adjust: dict[str, str] = {}
    # A fix can uncover the next clash (the profile first, then who may see the answers), so the
    # step repeats until nothing new is adjusted. Each key is adjusted once, so it ends.
    while True:
        fresh: dict[str, str] = {}
        for clash in found:
            for key, value in ADJUSTABLE.get(clash.reason, {}).items():
                # A type that resets everything adjusts nothing, and never overwrites its own key.
                if (
                    not new.resets_all
                    and key not in new.values()
                    and not skipped(key)
                    and key not in adjust
                ):
                    fresh[key] = value
        if not fresh:
            break
        adjust |= fresh
        target |= fresh
        found = clashes(resolved(), quiz)
    final = resolved()

    removals = [key for key in removals if key not in adjust]
    sets = {key: value for key, value in sets.items() if key not in adjust}
    changes = [Change(key, now[key], value) for key, value in sets.items() if now[key] != value]
    changes += [Change(key, now[key], None) for key in removals]
    adjusted = [Change(key, now[key], value) for key, value in adjust.items() if now[key] != value]

    writes: dict[str, str | None] = {key: None for key in removals}
    writes |= {key: value for key, value in (sets | adjust).items() if rows.get(key) != value}
    content = [
        item.key for item in requirements.of_quiz(quiz) if final.get(item.key) in item.refuse
    ]
    shown = Preview(
        type_id=new.id,
        changes=changes,
        adjusted=adjusted,
        skipped=list(dict.fromkeys(left_alone)),
        refused=found,
        live_run=quiz.runs.filter(status__in=_LIVE).exists(),
        content=list(dict.fromkeys(content)),
    )
    return shown, writes


def preview(quiz: Quiz, type_id: str) -> Preview:
    return _plan(quiz, type_id)[0]


def apply(quiz: Quiz, type_id: str, *, admin_id: str) -> Preview:
    """Recomputes the preview from the database; nothing is written when the type is refused."""
    with transaction.atomic():
        authoring.ensure_editable(quiz)
        quiz.refresh_from_db(fields=["quiz_type"])
        shown, writes = _plan(quiz, type_id)
        if shown.refused:
            raise TypeRefused(shown.refused)
        for key, value in writes.items():
            settings.set_override(key, quiz, value, admin_id=admin_id)
        quiz.quiz_type = shown.type_id
        quiz.save(update_fields=["quiz_type"])
        _audit("quiz.type_applied", quiz, admin_id, shown.type_id)
    return shown


def remove(quiz: Quiz, *, admin_id: str) -> None:
    """Forgets the type and keeps every value."""
    with transaction.atomic():
        authoring.ensure_editable(quiz)
        quiz.refresh_from_db(fields=["quiz_type"])
        old = quiz.quiz_type
        if not old:
            return
        quiz.quiz_type = ""
        quiz.save(update_fields=["quiz_type"])
        _audit("quiz.type_removed", quiz, admin_id, old)


def deviations(quiz: Quiz) -> dict[str, str | None]:
    """Key -> the type's value where the quiz resolves to another one; None: back to global."""
    plugin = get(quiz.quiz_type) if quiz.quiz_type else None
    if plugin is None:
        return {}
    skipped = _skips()
    if plugin.resets_all:
        return {key: None for key in sorted(_rows(quiz)) if not skipped(key)}
    values: Mapping[str, str] = plugin.values()
    return {
        key: value
        for key, value in values.items()
        if not skipped(key) and settings.resolve(key, quiz) != value
    }


def _audit(action: str, quiz: Quiz, admin_id: str, type_id: str) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="quiz",
        entity_id=str(quiz.id),
        details={"type": type_id},
    )
