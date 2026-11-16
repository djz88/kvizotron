"""Where a value of a module's setting differs from the global one, for the Modules page."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.domain import authoring, settings
from app.domain.models import AppSetting, Quiz, QuizRevision
from app.kernel.manifest import Manifest

LIMIT = 50


@dataclass(frozen=True)
class Difference:
    quiz: Quiz
    value: str
    question_id: str | None
    question_no: int | None


@dataclass(frozen=True)
class SettingOverview:
    key: str
    global_value: str
    differences: list[Difference]
    total: int


def _current_questions(quiz: Quiz) -> list[Mapping[str, Any]]:
    """The quiz as it is being worked on: its draft, otherwise its latest published revision."""
    draft = quiz.revisions.filter(status=QuizRevision.Status.DRAFT).first()
    revision = draft or authoring.latest_published(quiz)
    return revision.snapshot_json.get("questions", []) if revision else []


def _quiz_values(key: str, choices: tuple[str, ...]) -> dict[Any, str]:
    stored = AppSetting.objects.filter(
        key=key, quiz__isnull=False, quiz__archived_at__isnull=True
    ).values_list("quiz_id", "value_json")
    return {quiz_id: value for quiz_id, value in stored if value in choices}


def _of_quiz(
    quiz: Quiz,
    key: str,
    global_value: str,
    override: str | None,
    questions: list[Mapping[str, Any]],
) -> list[Difference]:
    found = []
    if override is not None and override != global_value:
        found.append(Difference(quiz, override, None, None))
    for number, question in enumerate(questions, start=1):
        value = settings.question_value(key, question)
        if value is not None and value != global_value:
            found.append(Difference(quiz, value, question["id"], number))
    return found


def overview(manifest: Manifest) -> list[SettingOverview]:
    """One row per setting the module declares, in the manifest's order."""
    if not manifest.settings:
        return []
    quizzes = list(Quiz.objects.filter(archived_at__isnull=True).order_by("created_at"))
    questions = {quiz.pk: _current_questions(quiz) for quiz in quizzes}
    rows = []
    for declared in manifest.settings:
        definition = settings.CATALOGUE[declared.key]
        global_value = settings.resolve(declared.key)
        overrides = (
            _quiz_values(declared.key, definition.choices) if "quiz" in definition.scopes else {}
        )
        differences = [
            difference
            for quiz in quizzes
            for difference in _of_quiz(
                quiz,
                declared.key,
                global_value,
                overrides.get(quiz.pk),
                questions[quiz.pk] if "question" in definition.scopes else [],
            )
        ]
        rows.append(
            SettingOverview(declared.key, global_value, differences[:LIMIT], len(differences))
        )
    return rows
