"""Which modules open runs depend on. Stored revisions must stay playable and scorable."""

from collections.abc import Iterator
from typing import Any

from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from app.domain import selection
from app.domain.models import QuizRun, RewardRule
from app.kernel import registry
from app.kernel.lifecycle import Blocker


def _questions(statuses: tuple[str, ...]) -> Iterator[tuple[QuizRun, dict[str, Any]]]:
    """Every revision of a round counts: attempts on older ones are still in play."""
    runs = QuizRun.all_kinds.filter(status__in=statuses).select_related(
        "quiz", "test_link", "current_revision"
    )
    now = timezone.now()
    for run in runs.prefetch_related("revision_rows__revision"):
        if run.kind == QuizRun.Kind.TEST and not run.test_link.is_playable(now):
            continue  # an ended link stays OPEN, and no one can play it
        # A planned run has no revision rows until it opens.
        revisions = [row.revision for row in run.revision_rows.all()] or [run.current_revision]
        for revision in revisions:
            for question in selection.all_questions(revision.snapshot_json):
                yield run, question


def _described(run: QuizRun) -> str:
    values = {"number": run.run_no, "quiz": run.quiz.slug}
    if run.kind == QuizRun.Kind.TEST:
        return _("test link of quiz %(quiz)s") % values
    if run.status == QuizRun.Status.SCHEDULED:
        return _("planned run %(number)s of quiz %(quiz)s") % values
    return _("open run %(number)s of quiz %(quiz)s") % values


def _target(run: QuizRun) -> tuple[str, str]:
    """A test link has no run page of its own."""
    if run.kind == QuizRun.Kind.TEST:
        return ("quiz", str(run.quiz_id))
    return ("run", str(run.pk))


def question_type_usage(module_id: str) -> list[Blocker]:
    """Why the module cannot be disabled now: a planned or open run needs its type or strategy."""
    owned = registry.owned_by(module_id)
    reasons = {
        Blocker("in_use", _described(run), _target(run))
        for run, question in _questions((QuizRun.Status.OPEN, QuizRun.Status.SCHEDULED))
        if ("question_type", question["type"]) in owned
        or ("scoring_strategy", question["scoring"]) in owned
    }
    return sorted(reasons, key=lambda reason: reason.text)


_LIVE = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN, QuizRun.Status.CLOSED)
THRESHOLD_MODULE = "rewards.threshold"
DRAWING_MODULE = "drawings.manual"


def reward_rule_usage(module_id: str) -> list[Blocker]:
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
    reasons = {
        Blocker(
            "in_use",
            _("run %(number)s of quiz %(quiz)s")
            % {"number": rule.run.run_no, "quiz": rule.quiz.slug},
            ("run", str(rule.run_id)),
        )
        for rule in rules
    }
    return sorted(reasons, key=lambda reason: reason.text)


def missing_plugin_problems() -> list[str]:
    """An open run needs a module that is no longer installed."""
    problems = set()
    with translation.override("en"):  # read by the operator at startup
        for run, question in _questions((QuizRun.Status.OPEN,)):
            for capability, key in (
                ("question_type", question["type"]),
                ("scoring_strategy", question["scoring"]),
            ):
                try:
                    registry.get(capability, key, include_disabled=True)
                except registry.UnknownPort:
                    problems.add(f"{_described(run)} needs {key}")
    return sorted(problems)
