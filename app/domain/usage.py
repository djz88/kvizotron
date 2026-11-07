"""Which modules open runs depend on. Stored revisions must stay playable and scorable."""

from collections.abc import Iterator
from typing import Any

from django.utils import timezone

from app.domain import selection
from app.domain.models import QuizRun
from app.kernel import registry


def _open_questions() -> Iterator[tuple[QuizRun, dict[str, Any]]]:
    """Every revision of a round counts: attempts on older ones are still in play."""
    runs = QuizRun.all_kinds.filter(status=QuizRun.Status.OPEN).select_related("quiz", "test_link")
    now = timezone.now()
    for run in runs.prefetch_related("revision_rows__revision"):
        if run.kind == QuizRun.Kind.TEST and not run.test_link.is_playable(now):
            continue  # an ended link stays OPEN, and no one can play it
        for row in run.revision_rows.all():
            for question in selection.all_questions(row.revision.snapshot_json):
                yield run, question


def _described(run: QuizRun) -> str:
    return "test link" if run.kind == QuizRun.Kind.TEST else f"open run {run.run_no}"


def question_type_usage(module_id: str) -> list[str]:
    """Why the module cannot be disabled now: an open run needs its type or strategy."""
    owned = registry.owned_by(module_id)
    reasons = {
        f"{_described(run)} of quiz {run.quiz.slug}"
        for run, question in _open_questions()
        if ("question_type", question["type"]) in owned
        or ("scoring_strategy", question["scoring"]) in owned
    }
    return sorted(reasons)


def missing_plugin_problems() -> list[str]:
    """An open run needs a module that is no longer installed."""
    problems = set()
    for run, question in _open_questions():
        for capability, key in (
            ("question_type", question["type"]),
            ("scoring_strategy", question["scoring"]),
        ):
            try:
                registry.get(capability, key, include_disabled=True)
            except registry.UnknownPort:
                problems.add(f"{_described(run)} of quiz {run.quiz.slug} needs {key}")
    return sorted(problems)
