"""What a run keeps and for how long, fixed on the run when it opens (C3)."""

from collections.abc import Iterator, Mapping
from typing import Any, cast

from app.contracts import ASK_EMAIL, ASK_NAME, REPEAT_ATTEMPTS, QuestionTypePlugin
from app.domain import settings
from app.domain.models import Attempt, Quiz, QuizRun
from app.kernel import registry

__all__ = [
    "KEYS",
    "StatelessConflict",
    "conflicts",
    "ensure_run_allowed",
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
    found += [key for key in (ASK_NAME, ASK_EMAIL) if rules.get(key, "off") != "off"]
    if visibility != settings.AnswersVisibility.ADMINS:
        found.append(settings.ANSWERS_VISIBILITY)
    if snapshot is not None and has_photo_question(snapshot):
        found.append(PHOTO_QUESTION)
    return found


def ensure_run_allowed(
    quiz: Quiz,
    data: Mapping[str, str],
    rules: Mapping[str, str],
    snapshot: Mapping[str, Any],
) -> None:
    """For a run about to be planned or opened. Raises `StatelessConflict`."""
    found = conflicts(
        data.get(PROFILE, ""),
        rules,
        settings.resolve(settings.ANSWERS_VISIBILITY, quiz),
        snapshot,
    )
    if found:
        raise StatelessConflict(found)
