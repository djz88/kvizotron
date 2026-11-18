"""The navigation, reveal, shuffle and sources a run keeps from when it was planned or opened.

A test run has no plan and follows its quiz as it is now (ADR-0069).
"""

from app.domain import settings
from app.domain.models import Quiz, QuizRun

KEYS = (
    settings.NAVIGATION_MODE,
    settings.PAGE_SIZE,
    settings.REVEAL_MOMENT,
    settings.REVEAL_LEVEL,
    settings.SHUFFLE_QUESTIONS,
    settings.SHUFFLE_OPTIONS,
    settings.SHOW_SOURCES,
)


def snapshot(quiz: Quiz) -> dict[str, str]:
    return {key: settings.resolve(key, quiz) for key in KEYS}


def of(run: QuizRun) -> dict[str, str]:
    """A missing key, or a value that is no longer offered, is resolved from the quiz."""
    if run.kind == QuizRun.Kind.TEST:
        return snapshot(run.quiz)
    kept = run.flow_json or {}
    return {
        key: kept[key]
        if kept.get(key) in settings.CATALOGUE[key].choices
        else settings.resolve(key, run.quiz)
        for key in KEYS
    }


def flow(run: QuizRun) -> settings.Flow:
    return settings.flow_of(of(run))
