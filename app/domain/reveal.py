"""What a participant is told about one question (FR-23). Computed from answers, never stored."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from app.contracts import JSON, ScoringStrategyPlugin
from app.domain import attempts, questions, settings
from app.kernel import registry


class State(StrEnum):
    RIGHT = "right"
    PARTIAL = "partial"
    WRONG = "wrong"
    UNANSWERED = "unanswered"
    PENDING = "pending"  # a person still decides part of the points


@dataclass(frozen=True)
class QuestionReveal:
    question_id: str
    state: State
    earned: Decimal
    maximum: Decimal
    show_answers: bool
    explanation: str | None


is_blank = questions.is_blank


def _maximum(question: Mapping[str, Any]) -> Decimal:
    strategy = cast(
        ScoringStrategyPlugin,
        registry.get("scoring_strategy", question["scoring"], include_disabled=True),
    )
    return strategy.max_score(question["settings"])


def of_question(
    question: Mapping[str, Any], answer: JSON | None, level: str, locale: str
) -> QuestionReveal:
    if is_blank(answer):
        state, earned, maximum = State.UNANSWERED, Decimal(0), _maximum(question)
    else:
        breakdown = attempts.evaluate(question, cast(JSON, answer))
        earned, maximum = breakdown.earned_points, breakdown.max_points
        if earned < maximum and attempts.needs_grading(question, cast(JSON, answer)):
            state = State.PENDING
        elif earned >= maximum:
            state = State.RIGHT
        else:
            state = State.PARTIAL if earned > 0 else State.WRONG
    explanation = None
    if level == settings.RevealLevel.EXPLANATIONS:
        explanation = question.get("explanation", {}).get(locale) or None
    return QuestionReveal(
        question["id"],
        state,
        earned,
        maximum,
        level != settings.RevealLevel.VERDICT,
        explanation,
    )
