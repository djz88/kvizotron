"""Which modules open runs depend on. Stored revisions must stay playable and scorable."""

from collections.abc import Iterator
from typing import Any

from django.db.models import Q
from django.utils import timezone

from app.domain import selection
from app.domain.models import QuizRun, RewardRule
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


_LIVE = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN, QuizRun.Status.CLOSED)
THRESHOLD_MODULE = "rewards.threshold"
DRAWING_MODULE = "drawings.manual"


def reward_rule_usage(module_id: str) -> list[str]:
    """Why a reward or drawing module cannot be disabled: a rule of a live run calls it.

    `rewards.threshold` judges threshold rules at every submission and the minimum of a draw
    rule; `drawings.manual` serves every draw rule. Participation and manual rules ask no plugin.
    A test run has no rules and an archived run no longer grants or draws.
    """
    if module_id == THRESHOLD_MODULE:
        wanted = Q(kind=RewardRule.Kind.THRESHOLD) | Q(
            kind=RewardRule.Kind.DRAW, min_unit__isnull=False
        )
    elif module_id == DRAWING_MODULE:
        wanted = Q(kind=RewardRule.Kind.DRAW)
    else:
        return []
    rules = RewardRule.objects.filter(
        wanted, run__status__in=_LIVE, run__kind=QuizRun.Kind.NORMAL
    ).select_related("run", "quiz")
    return sorted({f"run {rule.run.run_no} of quiz {rule.quiz.slug}" for rule in rules})


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
