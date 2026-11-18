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
from app.domain import data_policy, results, run_schedule, selection
from app.domain.models import Attempt, AttemptAnswer, Participant, Quiz, QuizRun, RunRevision
from app.kernel import registry

__all__ = [
    "QuestionStat",
    "RunStats",
    "RunSummary",
    "comparison",
    "freeze",
    "of_run",
    "of_revision",
    "question_max",
]

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
    passed: int | None = None  # people who passed under the run's rule; None without a pass mark
    judged: int = 0  # people with a verdict: the kept figures are final and the maximum is not 0


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


def question_max(question: Mapping[str, Any]) -> Decimal:
    """As publication counts the revision's maximum."""
    strategy = cast(
        ScoringStrategyPlugin,
        registry.get("scoring_strategy", question["scoring"], include_disabled=True),
    )
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
        top = question_max(question)
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


def of_revision(run: QuizRun, revision_id: object) -> tuple[int, dict[str, QuestionStat]]:
    """Submitted attempts on one revision of the run and, by question id, what they answered.

    The statistics hold only what the run keeps, so under `score` most questions have none.
    """
    found = [a for a in _submitted(run) if a.revision_id == revision_id]
    stats = _questions(run, found) if found else []
    return len(found), {stat.question_id: stat for stat in stats}


def _scores(found: Sequence[Attempt]) -> list[Decimal]:
    return [a.score for a in found if a.score is not None]


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _freeze_summary(summary: ScoreSummary) -> dict[str, Any]:
    return {
        "count": summary.count,
        "average": _decimal_text(summary.average),
        "median": _decimal_text(summary.median),
        "lowest": _decimal_text(summary.lowest),
        "highest": _decimal_text(summary.highest),
        "bands": list(summary.bands),
    }


def _thaw_summary(frozen: Mapping[str, Any]) -> ScoreSummary:
    return ScoreSummary(
        count=frozen["count"],
        average=_decimal(frozen["average"]),
        median=_decimal(frozen["median"]),
        lowest=_decimal(frozen["lowest"]),
        highest=_decimal(frozen["highest"]),
        bands=tuple(frozen["bands"]),
    )


def freeze(stats: RunStats) -> dict[str, Any]:
    """What survives a run's data: numbers only, a question is named by its id."""
    return {
        "participants": stats.participants,
        "started": stats.started,
        "submitted": stats.submitted,
        "unsent": stats.unsent,
        "summary": None if stats.summary is None else _freeze_summary(stats.summary),
        "questions": None
        if stats.questions is None
        else [
            {
                "question_id": stat.question_id,
                "answered": stat.answered,
                "average": str(stat.average),
                "full_share": stat.full_share,
            }
            for stat in stats.questions
        ],
        "questions_reason": stats.questions_reason,
        "by_revision": [[no, _freeze_summary(summary)] for no, summary in stats.by_revision],
        "passed": stats.passed,
        "judged": stats.judged,
    }


def _questions_of_run(run: QuizRun) -> dict[str, Mapping[str, Any]]:
    rows = RunRevision.objects.filter(run=run).select_related("revision").order_by("active_from")
    known: dict[str, Mapping[str, Any]] = {}
    for revision in [*(row.revision for row in rows), run.current_revision]:
        for offered in selection.all_questions(revision.snapshot_json):
            known.setdefault(offered["id"], offered)
    return known


def _thawed(run: QuizRun) -> RunStats:
    frozen = run.retention_summary_json
    questions: list[QuestionStat] | None = None
    if frozen["questions"] is not None:
        known = _questions_of_run(run)
        questions = [
            QuestionStat(
                question_id=row["question_id"],
                question=known[row["question_id"]],
                answered=row["answered"],
                average=Decimal(row["average"]),
                full_share=row["full_share"],
            )
            for row in frozen["questions"]
            if row["question_id"] in known
        ]
    return RunStats(
        participants=frozen["participants"],
        started=frozen["started"],
        submitted=frozen["submitted"],
        unsent=frozen["unsent"],
        summary=None if frozen["summary"] is None else _thaw_summary(frozen["summary"]),
        questions=questions,
        questions_reason=frozen["questions_reason"],
        by_revision=[(no, _thaw_summary(summary)) for no, summary in frozen["by_revision"]],
        passed=frozen.get("passed"),
        judged=frozen.get("judged", 0),
    )


def _verdicts(run: QuizRun, found: Sequence[Attempt]) -> tuple[int | None, int]:
    """(passed, judged) over people: the kept figures of a browser, an attempt on its own."""
    if results.pass_mark(run) is None:
        return None, 0
    verdicts: list[bool | None] = []
    people = {a.participant_id for a in found if a.participant_id}  # ids only: no query each
    for who in Participant.objects.filter(pk__in=people).select_related("run"):
        verdicts.append(results.kept_passed(results.kept(who), run))
    alone = [a for a in found if not a.participant_id]
    for attempt in results.counted(run, alone):  # on its own: judged where the mode counts it
        attempt.run = run
        verdicts.append(results.attempt_passed(attempt))
    judged = [v for v in verdicts if v is not None]
    return sum(1 for v in judged if v), len(judged)


def of_run(run: QuizRun) -> RunStats:
    if run.retention_summary_json:  # its rows are going or gone; the profile now says "none"
        return _thawed(run)
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
    passed, judged = _verdicts(run, found)
    return RunStats(
        participants=_participants(found),
        started=started,
        submitted=len(found),
        unsent=unsent,
        summary=summary,
        questions=_questions(run, found) if keeps else None,
        questions_reason=None if keeps else "profile",
        by_revision=by_revision,
        passed=passed,
        judged=judged,
    )


def _percent(average: Decimal | None, top: Decimal) -> int | None:
    if average is None or top <= 0:
        return None
    return int((average / top * _HUNDRED).quantize(1, ROUND_HALF_UP))


def _frozen_row(run: QuizRun) -> RunSummary:
    frozen = run.retention_summary_json
    average = _decimal(frozen["summary"]["average"]) if frozen["summary"] else None
    return RunSummary(
        cast(int, run.run_no),
        run.opened_at,
        run.closed_at,
        frozen["participants"],
        frozen["submitted"],
        average,
        _percent(average, _max_of(run)),
        run.id,
    )


def comparison(quiz: Quiz) -> list[RunSummary]:
    """Normal runs only (`quiz.runs` never holds a test run), newest first."""
    rows = []
    for run in quiz.runs.exclude(status=QuizRun.Status.SCHEDULED).order_by("-run_no"):
        if run.retention_summary_json:
            rows.append(_frozen_row(run))
            continue
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
        percent = _percent(average, _max_of(run))
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
