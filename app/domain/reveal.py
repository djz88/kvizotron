"""What a participant is told about one question (FR-23). Computed from answers, never stored."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from django.utils import translation
from django.utils.translation import gettext as _

from app.contracts import JSON, ScoringStrategyPlugin
from app.domain import attempts, clock, questions, settings
from app.domain.models import Attempt, QuizRun
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


def shown_from(run: QuizRun) -> datetime | None:
    """When answers shown after the run closes appear; None while no end is known."""
    if run.status in (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED):
        end = run.closed_at
    else:
        end = run.deadline_at
    return end + attempts.LATE_UPLOAD_WINDOW if end is not None else None


def is_shown(attempt: Attempt, now: datetime) -> bool:
    """Whether an attempt with the moment "after the run closes" may be told its answers now."""
    if attempts.flow_of(attempt)["moment"] != settings.RevealMoment.AFTER_CLOSE:
        return False
    run = attempt.run
    if run.kind == QuizRun.Kind.TEST:
        return True  # a test run treats it as "at the end"
    if run.status not in (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED):
        return False
    end = shown_from(run)
    return end is not None and now >= end


def shows_answers(attempt: Attempt, now: datetime) -> bool:
    """The one place that says an attempt's answers may be listed now.

    A moment this code does not know shows nothing, so a new moment is never open by default.
    """
    moment = attempts.flow_of(attempt)["moment"]
    if moment in (settings.RevealMoment.AT_END, settings.RevealMoment.AFTER_EACH):
        return True
    return moment == settings.RevealMoment.AFTER_CLOSE and is_shown(attempt, now)


def after_close_note(attempt: Attempt, locale: str) -> str:
    """What a participant is told while answers wait for the run to close; empty otherwise."""
    if attempts.flow_of(attempt)["moment"] != settings.RevealMoment.AFTER_CLOSE:
        return ""
    run = attempt.run
    if run.kind == QuizRun.Kind.TEST:
        return rehearsal_note(locale)
    when = shown_from(run)
    closed = run.status in (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED)
    with translation.override(locale):
        if when is None:
            return _("You will see the correct answers at this link after the run closes.")
        if closed:
            return _(
                "You will see the correct answers at this link after the run closes "
                "(from %(when)s)."
            ) % {"when": clock.shown(when)}
        # An open run may still be closed earlier or get a later deadline.
        return _(
            "You will see the correct answers at this link after the run closes "
            "(at the earliest from %(when)s)."
        ) % {"when": clock.shown(when)}


def rehearsal_note(locale: str) -> str:
    """A test link or a preview shows the answers at once; this says what a real run does."""
    with translation.override(locale):
        return str(_("In a real run, the correct answers are shown only after the run closes."))


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
