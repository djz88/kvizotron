"""Statistics of a run and a comparison of a quiz's runs (FR-43). Test runs never count.

Numbers are over every submitted attempt, not only the official ones of the scoreboard.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast
from uuid import UUID

from app.contracts import ResultViewPlugin, ScoreSummary, ScoringStrategyPlugin
from app.domain import data_policy, run_schedule, selection
from app.domain.models import Attempt, AttemptAnswer, Quiz, QuizRun, RunRevision
from app.kernel import registry

__all__ = ["QuestionStat", "RunStats", "RunSummary", "comparison", "of_run"]

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class QuestionStat:
    question_id: str
    question: Mapping[str, Any]  # the page names it in its own language
    answered: int
    average: Decimal
    full_share: int  # percent of answers with full points


@dataclass(frozen=True)
class RunStats:
    participants: int
    started: int
    submitted: int
    unsent: int
    summary: ScoreSummary | None
    questions: list[QuestionStat] | None
    questions_reason: str | None  # "profile" when the run does not keep every answer
    by_revision: list[tuple[int, ScoreSummary]]


@dataclass(frozen=True)
class RunSummary:
    run_no: int
    opened_at: datetime | None
    closed_at: datetime | None
    participants: int
    submitted: int
    average: Decimal | None
    percent: int | None
    run_id: UUID


def _view() -> ResultViewPlugin:
    return cast(ResultViewPlugin, registry.get("result_view", "local"))


def _submitted(run: QuizRun) -> list[Attempt]:
    return list(
        Attempt.objects.filter(
            run=run, status__in=Attempt.FINISHED, submitted_at__isnull=False
        ).select_related("revision")
    )


def _participants(found: Sequence[Attempt]) -> int:
    """A browser counts once; an attempt without one counts as its own participant."""
    people = {a.participant_id for a in found if a.participant_id}
    return len(people) + sum(1 for a in found if not a.participant_id)


def _max_of(run: QuizRun) -> Decimal:
    row = RunRevision.objects.filter(run=run, revision_id=run.current_revision_id).first()
    return row.max_score if row else run.current_revision.max_score


def _question_max(question: Mapping[str, Any]) -> Decimal:
    """As publication counts the revision's maximum."""
    strategy = cast(ScoringStrategyPlugin, registry.get("scoring_strategy", question["scoring"]))
    return strategy.max_score(question["settings"])


def _questions(run: QuizRun, found: Sequence[Attempt]) -> list[QuestionStat]:
    known: dict[str, Mapping[str, Any]] = {}
    for revision in {a.revision_id: a.revision for a in found}.values() or [run.current_revision]:
        for offered in selection.all_questions(revision.snapshot_json):
            known.setdefault(offered["id"], offered)
    points: dict[str, list[Decimal]] = {}
    for row in AttemptAnswer.objects.filter(attempt__in=found, removed=False):
        points.setdefault(row.question_id, []).append(row.auto_points + (row.manual_points or 0))
    stats = []
    for question_id, question in known.items():
        given = points.get(question_id)
        if not given:
            continue
        top = _question_max(question)
        full = sum(1 for value in given if top > 0 and value >= top)
        stats.append(
            QuestionStat(
                question_id=question_id,
                question=question,
                answered=len(given),
                average=(sum(given, Decimal(0)) / len(given)).quantize(_CENT, ROUND_HALF_UP),
                full_share=int((Decimal(full) / len(given) * _HUNDRED).quantize(1, ROUND_HALF_UP)),
            )
        )
    return stats


def _scores(found: Sequence[Attempt]) -> list[Decimal]:
    return [a.score for a in found if a.score is not None]


def of_run(run: QuizRun) -> RunStats:
    profile = data_policy.of(run)[data_policy.PROFILE]
    unsent = run_schedule.unsent(run)
    if data_policy.is_stateless(profile):
        return RunStats(0, 0, run.stateless_submitted, unsent, None, None, "profile", [])
    found = _submitted(run)
    started = run.attempts.exclude(status=Attempt.Status.SWITCHED).count()
    view = _view()
    summary = view.summarize(_scores(found), _max_of(run))
    by_revision: list[tuple[int, ScoreSummary]] = []
    used = list(
        RunRevision.objects.filter(run=run).select_related("revision").order_by("active_from")
    )
    if len({row.revision_id for row in used}) > 1:
        seen: set[object] = set()
        for row in used:
            if row.revision_id in seen:
                continue
            seen.add(row.revision_id)
            mine = [a for a in found if a.revision_id == row.revision_id]
            no = cast(int, row.revision.revision_no)
            by_revision.append((no, view.summarize(_scores(mine), row.max_score)))
    keeps = data_policy.keeps_all_answers(profile)
    return RunStats(
        participants=_participants(found),
        started=started,
        submitted=len(found),
        unsent=unsent,
        summary=summary,
        questions=_questions(run, found) if keeps else None,
        questions_reason=None if keeps else "profile",
        by_revision=by_revision,
    )


def comparison(quiz: Quiz) -> list[RunSummary]:
    """Normal runs only (`quiz.runs` never holds a test run), newest first."""
    rows = []
    for run in quiz.runs.exclude(status=QuizRun.Status.SCHEDULED).order_by("-run_no"):
        if data_policy.is_stateless(data_policy.of(run)[data_policy.PROFILE]):
            rows.append(
                RunSummary(
                    cast(int, run.run_no),
                    run.opened_at,
                    run.closed_at,
                    0,
                    run.stateless_submitted,
                    None,
                    None,
                    run.id,
                )
            )
            continue
        found = _submitted(run)
        scores = _scores(found)
        average = (
            (sum(scores, Decimal(0)) / len(scores)).quantize(_CENT, ROUND_HALF_UP)
            if scores
            else None
        )
        top = _max_of(run)
        percent = (
            int((average / top * _HUNDRED).quantize(1, ROUND_HALF_UP))
            if average is not None and top > 0
            else None
        )
        rows.append(
            RunSummary(
                cast(int, run.run_no),
                run.opened_at,
                run.closed_at,
                _participants(found),
                len(found),
                average,
                percent,
                run.id,
            )
        )
    return rows
