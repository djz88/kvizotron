"""What a run keeps and for how long, fixed on the run when it opens (C3)."""

import math
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from typing import Any, cast

from app.contracts import (
    AFTER_PASS,
    ASK_EMAIL,
    ASK_NAME,
    MAX_ATTEMPTS,
    REPEAT_ATTEMPTS,
    QuestionTypePlugin,
)
from app.domain import settings
from app.domain.models import Attempt, Quiz, QuizRun
from app.kernel import registry

__all__ = [
    "KEYS",
    "PERIOD_DAYS",
    "StatelessConflict",
    "WARNING_DAYS",
    "after_close_conflicts",
    "conflicts",
    "days_left",
    "deletion_at",
    "deletion_soon",
    "ensure_run_allowed",
    "is_due",
    "is_stateless",
    "has_photo_question",
    "keeps_all_answers",
    "keeps_duration",
    "of",
    "profile_of_attempt",
    "rules_for_quiz",
    "snapshot",
]

PHOTO_QUESTION = "photo_question"
PROFILE = "profile"
PERIOD = "period"
KEYS = (PROFILE, PERIOD)
_SETTING_OF = {PROFILE: settings.DATA_PROFILE, PERIOD: settings.RETENTION_PERIOD}
# What `store_answers` meant before the profile existed.
_UPGRADE = {"all": settings.DataProfile.ANSWERS.value, "images": settings.DataProfile.SCORE.value}
# `permanent` is not here: it has no end. Migration 0019 holds its own copy.
PERIOD_DAYS: Mapping[str, int] = {
    settings.RetentionPeriod.D30.value: 30,
    settings.RetentionPeriod.D90.value: 90,
    settings.RetentionPeriod.D180.value: 180,
    settings.RetentionPeriod.Y1.value: 365,
    settings.RetentionPeriod.Y3.value: 1095,
}
WARNING_DAYS = 14
_DAY_SECONDS = 86400


def rules_for_quiz(quiz: Quiz) -> dict[str, str]:
    return {key: settings.resolve(name, quiz=quiz) for key, name in _SETTING_OF.items()}


def snapshot(quiz: Quiz, chosen: Mapping[str, str] | None) -> dict[str, str]:
    """What a run stores: the quiz's values as they are now, with the given ones on top."""
    given = {key: chosen[key] for key in KEYS if chosen and chosen.get(key)}
    return rules_for_quiz(quiz) | given


def of(run: QuizRun) -> dict[str, str]:
    """A test run has no plan, so it follows the quiz as it is now."""
    if run.kind == QuizRun.Kind.TEST:
        return rules_for_quiz(run.quiz)
    stored = run.retention_json or {}
    return {
        key: stored[key] if key in stored else settings.CATALOGUE[name].default
        for key, name in _SETTING_OF.items()
    }


def deletion_at(run: QuizRun) -> datetime | None:
    """When the run's data go. None for a run that has no such date, now or ever."""
    if run.kind == QuizRun.Kind.TEST or run.closed_at is None or run.data_deleted_at is not None:
        return None
    days = PERIOD_DAYS.get(of(run)[PERIOD])
    return None if days is None else run.closed_at + timedelta(days=days)


def is_due(run: QuizRun, now: datetime) -> bool:
    """A held run waits for an admin, however long ago it fell due."""
    at = deletion_at(run)
    return at is not None and at <= now and run.retention_held_at is None


def days_left(run: QuizRun, now: datetime) -> int | None:
    """Whole days, a started one counted, so "in 9 days" holds all through the ninth."""
    at = deletion_at(run)
    if at is None:
        return None
    return max(0, math.ceil((at - now).total_seconds() / _DAY_SECONDS))


def deletion_soon(run: QuizRun, now: datetime) -> bool:
    left = days_left(run, now)
    return left is not None and left <= WARNING_DAYS


def profile_of_attempt(attempt: Attempt) -> str:
    frozen = attempt.settings_json or {}
    if frozen.get(PROFILE):
        return str(frozen[PROFILE])
    return _UPGRADE.get(str(frozen.get("store_answers")), settings.DataProfile.SCORE.value)


def keeps_all_answers(profile: str) -> bool:
    return profile in (settings.DataProfile.ANSWERS, settings.DataProfile.DETAILED)


def keeps_duration(profile: str) -> bool:
    return profile == settings.DataProfile.DETAILED


def is_stateless(profile: str) -> bool:
    return profile == settings.DataProfile.NONE


class StatelessConflict(Exception):
    """The profile "none" cannot keep a promise another setting breaks. `keys` name those."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(", ".join(keys))
        self.keys = keys


def _questions_of(snapshot: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield from snapshot.get("questions", [])
    for row in snapshot.get("draws", []):
        yield from row.get("pool", [])


def has_photo_question(snapshot: Mapping[str, Any]) -> bool:
    for question in _questions_of(snapshot):
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        if plugin.file_fields(question["definition"]):
            return True
    return False


def conflicts(
    profile: str,
    rules: Mapping[str, str],
    visibility: str,
    snapshot: Mapping[str, Any] | None,
) -> list[str]:
    """What "none" rules out, by setting key. Empty for every other profile."""
    if not is_stateless(profile):
        return []
    found = []
    if rules.get(REPEAT_ATTEMPTS) == "forbid":
        found.append(REPEAT_ATTEMPTS)
    elif int(rules.get(MAX_ATTEMPTS, "0") or "0") > 0:
        found.append(MAX_ATTEMPTS)
    if rules.get(AFTER_PASS, "more") == "stop":
        found.append(AFTER_PASS)
    found += [key for key in (ASK_NAME, ASK_EMAIL) if rules.get(key, "off") != "off"]
    if visibility != settings.AnswersVisibility.ADMINS:
        found.append(settings.ANSWERS_VISIBILITY)
    if snapshot is not None and has_photo_question(snapshot):
        found.append(PHOTO_QUESTION)
    return found


def after_close_conflicts(moment: str, profile: str) -> list[str]:
    """Answers shown after the run closes need a profile that keeps them."""
    if moment == settings.RevealMoment.AFTER_CLOSE and not keeps_all_answers(profile):
        return [settings.REVEAL_MOMENT]
    return []


def ensure_run_allowed(
    quiz: Quiz,
    data: Mapping[str, str],
    rules: Mapping[str, str],
    snapshot: Mapping[str, Any],
    *,
    reveal_moment: str,
) -> None:
    """For a run about to be planned or opened. Raises `StatelessConflict`."""
    found = conflicts(
        data.get(PROFILE, ""),
        rules,
        settings.resolve(settings.ANSWERS_VISIBILITY, quiz),
        snapshot,
    )
    found += after_close_conflicts(reveal_moment, data.get(PROFILE, ""))
    if found:
        raise StatelessConflict(found)
