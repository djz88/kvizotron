"""Who may see a stored answer or a photo. Pages ask here, so no page decides on its own."""

from collections.abc import Mapping
from typing import Any

from app.contracts import PHOTO_ADMINS, PHOTO_PUBLIC
from app.domain import attempts, settings
from app.domain.models import Attempt, AttemptAnswer, Quiz, QuizRun


def photo_level(quiz: Quiz, question: Mapping[str, Any] | None) -> str:
    return settings.photo_level(quiz, question)


def may_be_approved(answer: AttemptAnswer, quiz: Quiz, question: Mapping[str, Any] | None) -> bool:
    """Public at this moment, and the page said so when this attempt began (ADR-0047)."""
    told = (answer.attempt.settings_json or {}).get("told_public", [])
    return (
        bool(answer.asset_id)
        and answer.question_id in told
        and photo_level(quiz, question) == PHOTO_PUBLIC
    )


def author_sees_photo(answer: AttemptAnswer, quiz: Quiz, question: Mapping[str, Any]) -> bool:
    return bool(answer.asset_id) and photo_level(quiz, question) != PHOTO_ADMINS


def public_sees_photo(answer: AttemptAnswer, quiz: Quiz, question: Mapping[str, Any]) -> bool:
    run = answer.attempt.run
    return (
        answer.approved
        and may_be_approved(answer, quiz, question)
        and run.status == QuizRun.Status.CLOSED
        and run.kind == QuizRun.Kind.NORMAL
    )


def participant_sees_answers(attempt: Attempt) -> bool:
    return settings.answers_visibility(attempt.run.quiz) != settings.AnswersVisibility.ADMINS


def has_more_to_see(attempt: Attempt) -> bool:
    """Whether a private link would show anything beyond the score already on the page."""
    rows = list(attempt.answers.all())
    if not rows:
        return False
    if participant_sees_answers(attempt):
        return True
    questions = {question["id"]: question for question in attempts.questions_of(attempt)}
    return any(
        row.question_id in questions
        and author_sees_photo(row, attempt.run.quiz, questions[row.question_id])
        for row in rows
    )
