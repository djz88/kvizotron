"""Which modules open runs depend on. Stored revisions must stay playable and scorable."""

from collections.abc import Iterator
from typing import Any

from app.domain.models import QuizRun
from app.kernel import registry


def _open_questions() -> Iterator[tuple[QuizRun, dict[str, Any]]]:
    runs = QuizRun.objects.filter(status=QuizRun.Status.OPEN).select_related(
        "quiz", "current_revision"
    )
    for run in runs:
        for question in run.current_revision.snapshot_json.get("questions", []):
            yield run, question


def question_type_usage(module_id: str) -> list[str]:
    """Why the module cannot be disabled now: an open run needs its type or strategy."""
    owned = registry.owned_by(module_id)
    reasons = {
        f"open run {run.run_no} of quiz {run.quiz.slug}"
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
                problems.add(f"open run {run.run_no} of quiz {run.quiz.slug} needs {key}")
    return sorted(problems)
