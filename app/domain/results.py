"""Scoreboard settings fixed on the run, and the board built from submitted attempts (C4).

The rules of order live in the `result_view` module; this module reads attempts and decides who
may see what (ADR-0026, ADR-0031, ADR-0051).
"""

import heapq
import secrets
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, cast

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import translation
from django.utils.translation import gettext

from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
    PASS_MARK,
    RESULT_DISPLAY_KEYS,
    RESULT_KEYS,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_SECOND_SORT,
    SCOREBOARD_SHOW_DURATION,
    SCOREBOARD_SHOW_PERCENT,
    SCOREBOARD_SHOW_SCORE,
    SCOREBOARD_SHOW_TIME,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    AttemptFigures,
    RankedRow,
    ResultViewPlugin,
    ScoreEntry,
)
from app.domain import attempts, authoring, data_policy, settings
from app.domain.models import Attempt, Participant, Quiz, QuizRun, RunRevision
from app.kernel import audit, registry

__all__ = [
    "BOARD_CACHE_SECONDS",
    "Board",
    "BoardRow",
    "ResultConflict",
    "ShareRefused",
    "Table",
    "board",
    "is_public",
    "place_of",
    "anonymous_label",
    "conflicts",
    "counted",
    "ensure_run_allowed",
    "needs_participant",
    "reasons",
    "of",
    "Kept",
    "kept",
    "official_attempt",
    "participant_numbers",
    "revision_mode",
    "rules_for_quiz",
    "set_display",
    "share_board",
    "shared_runs",
    "snapshot",
    "split_board",
]

SEED = "seed"
PERCENT = "percent"
LATEST = "latest"
MAX_LABEL = 40


STATELESS = "stateless"
AFTER_EACH = "after_each"
NEEDS_TIMES = "needs_times"
TEST_RUN = "test_run"


class ResultConflict(Exception):
    """Settings that cannot go together: setting keys, and why (the codes above)."""

    def __init__(self, keys: list[str], reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.keys = keys
        self.reasons = reasons


def rules_for_quiz(quiz: Quiz) -> dict[str, str]:
    return {key: settings.resolve(key, quiz=quiz) for key in RESULT_KEYS}


def snapshot(quiz: Quiz, chosen: Mapping[str, str] | None) -> dict[str, str]:
    """What a run stores: the quiz's values now, the chosen ones on top, and a seed for ties."""
    given = {key: chosen[key] for key in RESULT_KEYS if chosen and chosen.get(key)}
    return rules_for_quiz(quiz) | given | {SEED: secrets.token_hex(16)}


def of(run: QuizRun) -> dict[str, str]:
    """A test run follows the quiz as it is now, and never has a public board."""
    if run.kind == QuizRun.Kind.TEST:
        return rules_for_quiz(run.quiz) | {SCOREBOARD_VISIBILITY: "hidden", SEED: str(run.id)}
    stored = run.results_json or {}
    values = {
        key: stored[key] if key in stored else settings.CATALOGUE[key].default
        for key in RESULT_KEYS
    }
    return values | {SEED: stored.get(SEED) or str(run.id)}


def revision_mode(run: QuizRun) -> str:
    """percent, separate or latest: how the board shows revisions and which attempts count."""
    return of(run)[REVISION_MODE]


def needs_participant(run: QuizRun) -> bool:
    """A visible board shows one row per browser, so the browser needs a cookie (ADR-0051)."""
    return of(run)[SCOREBOARD_VISIBILITY] != "hidden"


def _uses_duration(values: Mapping[str, str]) -> list[str]:
    found = []
    if values.get(SCOREBOARD_SHOW_DURATION) == "on":
        found.append(SCOREBOARD_SHOW_DURATION)
    if values.get(SCOREBOARD_SECOND_SORT) == "duration":
        found.append(SCOREBOARD_SECOND_SORT)
    return found


def reasons(chosen: Mapping[str, str], *, profile: str, reveal_moment: str) -> list[str]:
    """Why the values cannot go with the run's data profile and the quiz's answers."""
    found = []
    if chosen.get(SCOREBOARD_VISIBILITY, "hidden") != "hidden":
        if data_policy.is_stateless(profile):
            found.append(STATELESS)
        if reveal_moment == settings.RevealMoment.AFTER_EACH:
            found.append(AFTER_EACH)
    if not data_policy.keeps_duration(profile) and _uses_duration(chosen):
        found.append(NEEDS_TIMES)
    return found


def conflicts(chosen: Mapping[str, str], *, profile: str, reveal_moment: str) -> list[str]:
    """The same, by setting key."""
    why = reasons(chosen, profile=profile, reveal_moment=reveal_moment)
    found = [SCOREBOARD_VISIBILITY] if {STATELESS, AFTER_EACH} & set(why) else []
    if NEEDS_TIMES in why:
        found += _uses_duration(chosen)
    return found


def _check(chosen: Mapping[str, str], *, profile: str, reveal_moment: str) -> None:
    why = reasons(chosen, profile=profile, reveal_moment=reveal_moment)
    if why:
        raise ResultConflict(conflicts(chosen, profile=profile, reveal_moment=reveal_moment), why)


def ensure_run_allowed(quiz: Quiz, chosen: Mapping[str, str], profile: str) -> None:
    """For a run about to be planned or opened. Raises `ResultConflict`."""
    _check(chosen, profile=profile, reveal_moment=settings.resolve(settings.REVEAL_MOMENT, quiz))


def set_display(run: QuizRun, chosen: Mapping[str, str], *, admin_id: str) -> None:
    """What is shown and the revision mode; the rest decides the order and stays as opened.

    The revision mode also decides which attempt counts (`kept`), so a changed one recomputes the
    run's rewards in the same transaction (ADR-0053, addendum of 2026-11-17).
    """
    authoring.ensure_editable(run.quiz)
    if run.kind == QuizRun.Kind.TEST:
        raise ResultConflict([SCOREBOARD_VISIBILITY], [TEST_RUN])
    given = {
        key: chosen[key]
        for key in RESULT_DISPLAY_KEYS
        if chosen.get(key) and chosen[key] in settings.CATALOGUE[key].choices
    }
    with transaction.atomic():
        current = QuizRun.objects.select_for_update().filter(pk=run.pk).first()
        if current is None:
            raise ResultConflict([SCOREBOARD_VISIBILITY], [TEST_RUN])
        before = of(current)
        after = before | given
        _check(
            after,
            profile=data_policy.of(current)[data_policy.PROFILE],
            reveal_moment=settings.resolve(settings.REVEAL_MOMENT, current.quiz),
        )
        changed = {key: value for key, value in given.items() if before[key] != value}
        if not changed:
            return
        current.results_json = (current.results_json or {}) | after
        current.save(update_fields=["results_json"])
        if REVISION_MODE in changed:
            from app.domain import rewards  # rewards imports this module

            rewards.refresh_run(current)
        _forget(current)  # a rollback only costs a rebuilt board
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.scoreboard_changed",
            entity_type="run",
            entity_id=str(run.id),
            details=changed,
        )
    run.results_json = current.results_json


def _default_label(locale: str) -> str:
    with translation.override(locale):
        return gettext("Player NN")


def anonymous_label(quiz: Quiz, locale: str, number: int) -> str:
    """The quiz's text for the language, or the default; `NN` is the number."""
    text = (quiz.anonymous_label or {}).get(locale, "").strip() or _default_label(locale)
    if "NN" in text:
        return text.replace("NN", str(number))
    return f"{text} {number}"


# The board -----------------------------------------------------------------------------------

BOARD_CACHE_SECONDS = 5
_COLUMNS = (
    ("score", SCOREBOARD_SHOW_SCORE),
    ("percent", SCOREBOARD_SHOW_PERCENT),
    ("time", SCOREBOARD_SHOW_TIME),
    ("duration", SCOREBOARD_SHOW_DURATION),
)
_ENDED = (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED)
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class BoardRow:
    rank: int
    label: str
    score: Decimal
    max_score: Decimal
    percent: int
    submitted_at: datetime
    duration_ms: int | None
    mine: bool
    key: str  # marks "mine" only; a template never shows it
    attempt_id: str = ""  # which attempt the row ranks, for the admin export; never shown
    passed: bool | None = None  # against the run's pass mark; None without one


@dataclass(frozen=True)
class Table:
    revision_no: int | None  # None for one table over all revisions
    max_score: Decimal | None  # None by percent: each row has its own maximum
    rows: list[BoardRow]


@dataclass(frozen=True)
class Board:
    tables: list[Table]
    hidden: str | None  # "hidden", "after_end", "pending", "archived", "data_deleted"
    columns: tuple[str, ...]
    final: bool  # nothing on it can change any more


@dataclass(frozen=True)
class _Ranked:
    revision_id: object | None  # None for one table over all revisions
    revision_no: int | None
    max_score: Decimal | None  # None by percent
    rows: list[RankedRow]
    # By percent the ranked entries hold percents (`by_percent`), and `shown` holds the points
    # shown, by attempt id; by points both are left out.
    by_percent: bool = False
    shown: Mapping[str, ScoreEntry] | None = None
    # On a shared board: the run number of each row's run, by row key.
    run_of: Mapping[str, int] | None = None


def _cache_key(run: QuizRun, locale: str) -> str:
    return f"kvz-board:{run.id}:{locale}"


def _forget(run: QuizRun) -> None:
    """A changed board is shown at once, so a hidden one does not stay public for seconds.

    A member of a shared board also drops the board of its main run, which shows its rows.
    """
    locales = set(run.quiz.supported_locales) | set(
        run.current_revision.snapshot_json.get("locales", [])
    )
    cache.delete_many([_cache_key(run, locale) for locale in locales])
    if run.board_main_id is not None:
        main = (
            QuizRun.all_kinds.select_related("quiz", "current_revision")
            .filter(pk=run.board_main_id)
            .first()
        )
        if main is not None and main.board_main_id is None:  # a main is never a member
            _forget(main)


def clear_board_cache(run_id: object) -> None:
    """For callers outside this module that changed who is on a board, such as an erasure."""
    run = QuizRun.all_kinds.select_related("quiz", "current_revision").filter(pk=run_id).first()
    if run is not None:
        _forget(run)


def _view() -> ResultViewPlugin:
    return cast(ResultViewPlugin, registry.get("result_view", "local"))


def _pending(run: QuizRun) -> bool:
    return Attempt.objects.filter(run=run, status=Attempt.Status.PENDING_GRADING).exists()


def _hidden(run: QuizRun, values: Mapping[str, str], pending: bool) -> str | None:
    if run.data_deleted_at is not None:  # first: no setting can bring deleted data back
        return "data_deleted"
    visibility = values[SCOREBOARD_VISIBILITY]
    if visibility == "hidden":
        return "hidden"
    if run.status == QuizRun.Status.ARCHIVED and values[ARCHIVED_RESULTS] != "on":
        return "archived"
    if visibility == "after_end" and run.status not in _ENDED:
        return "after_end"
    if pending:
        return "pending"
    return None


def _pending_any(run: QuizRun) -> bool:
    """Pending grading in the run or, for a main run, in any run of its shared board."""
    return any(_pending(linked) for linked in shared_runs(run))


def is_public(run: QuizRun) -> bool:
    return _hidden(run, of(run), _pending_any(run)) is None


def public_runs(quiz: Quiz, *, besides: QuizRun | None = None) -> list[QuizRun]:
    """The quiz's normal runs whose board is public now, newest first, in one query (AC-176).

    Pending grading in a member of a main run's shared board holds the main board too.
    """
    waiting = Attempt.objects.filter(
        Q(run=OuterRef("pk")) | Q(run__board_main=OuterRef("pk")),
        status=Attempt.Status.PENDING_GRADING,
    )
    runs = (
        QuizRun.objects.filter(quiz=quiz, opened_at__isnull=False, data_deleted_at__isnull=True)
        .exclude(status=QuizRun.Status.SCHEDULED)
        .annotate(waiting=Exists(waiting))
        .order_by("-run_no")
    )
    if besides is not None:
        runs = runs.exclude(pk=besides.pk)
    return [run for run in runs if _hidden(run, of(run), run.waiting) is None]


def _columns(run: QuizRun, values: Mapping[str, str]) -> tuple[str, ...]:
    keeps_duration = data_policy.keeps_duration(data_policy.of(run)[data_policy.PROFILE])
    return tuple(
        name
        for name, key in _COLUMNS
        if values[key] == "on" and (name != "duration" or keeps_duration)
    )


def _key(attempt: Attempt) -> str:
    return str(attempt.participant_id) if attempt.participant_id else f"a:{attempt.id}"


def _numbers(run: QuizRun) -> dict[str, int]:
    """Each browser's stored number (`Participant.number`), so an erasure shifts no label.

    An attempt without a browser, and a browser row without a number, follow the highest stored
    number in the order they came; a later browser can move them, a stored number never moves.
    """
    stored: dict[str, int] = {}
    unnumbered: list[tuple[datetime, str, str]] = []
    for who in Participant.objects.filter(run=run).order_by("created_at", "id"):
        if who.number is None:
            unnumbered.append((who.created_at, str(who.id), str(who.id)))
        else:
            stored[str(who.id)] = who.number
    loose = (
        (attempt.started_at, str(attempt.id), f"a:{attempt.id}")
        for attempt in Attempt.objects.filter(run=run, participant__isnull=True).order_by(
            "started_at", "id"
        )
    )
    merged: Iterator[tuple[datetime, str, str]] = heapq.merge(unnumbered, loose)
    after = max(stored.values(), default=0)
    return stored | {key: number for number, (_when, _id, key) in enumerate(merged, after + 1)}


def participant_numbers(run: QuizRun) -> dict[str, int]:
    """The number of each participant's anonymous label, keyed by the participant id."""
    return _numbers(run)


def _candidates(run: QuizRun) -> list[Attempt]:
    return list(
        Attempt.objects.filter(
            run=run,
            status=Attempt.Status.SUBMITTED,
            submitted_at__isnull=False,
            score__isnull=False,
        ).select_related("participant")
    )


@dataclass(frozen=True)
class Kept:
    """What counts for one participant under the run's rule (ADR-0063)."""

    attempt: Attempt  # the chosen one; under average the last submitted
    figures: AttemptFigures  # what counts: rewards, draws, pass mark, scoreboard
    count: int  # submitted attempts it comes from
    rule: str  # first, best, last or average
    waiting: bool  # an attempt it depends on waits for grading


def _figures_of(attempt: Attempt) -> AttemptFigures:
    return AttemptFigures(
        score=attempt.score if attempt.score is not None else Decimal(0),
        max_score=attempt.max_score if attempt.max_score is not None else Decimal(0),
        correct=attempt.correct_count or 0,
        questions=len(attempts.items_of(attempt)),
    )


def _average_figures(found: list[Attempt], entry: ScoreEntry) -> AttemptFigures:
    count = len(found)
    questions = sum(len(attempts.items_of(a)) for a in found)
    return AttemptFigures(
        score=entry.score,
        max_score=entry.max_score,
        correct=sum(a.correct_count or 0 for a in found) // count,
        questions=int((Decimal(questions) / count).quantize(Decimal(1), ROUND_HALF_UP)),
    )


def _waits(rule: str, finished: list[Attempt]) -> bool:
    pending = [a.status == Attempt.Status.PENDING_GRADING for a in finished]
    if rule == "first":
        return pending[0]
    if rule == "last":
        return pending[-1]
    return any(pending)


def kept(participant: Participant) -> Kept | None:
    """The attempt and the figures that count for the participant, as the run's board counts.

    The run's own revision mode decides which attempts count (`latest`: only its current
    revision), and the run's rule picks among them by the percent of each attempt's own revision
    maximum, as `_pick_by_percent` does for the board; `separate` picks like `percent`, so a
    participant counts once (ADR-0065, TD-047). Within one revision that is the order of points.
    Under `average` the figures stay the mean of points over the mean of maxima.

    Only submitted attempts with a score count; switched, abandoned, unsent and waiting ones
    never do. `waiting` only says that the rule depends on an attempt that waits for grading;
    the pass mark uses it, nothing that grants or ranks does (ADR-0063). None when the
    participant has no submitted, scored attempt the mode counts.
    """
    run = participant.run
    values = of(run)
    finished = counted(
        run,
        Attempt.objects.filter(
            participant=participant,
            status__in=Attempt.FINISHED,
            submitted_at__isnull=False,
        ),
        values[REVISION_MODE],
    )
    for attempt in finished:
        attempt.participant = participant  # one query, not one per attempt
    # the same order as `_entry` gives `pick_official` (`attempt_id` is `str(id)`)
    finished.sort(key=lambda a: (cast(datetime, a.submitted_at), str(a.id)))
    found = [a for a in finished if a.status == Attempt.Status.SUBMITTED and a.score is not None]
    if not found:
        return None
    rule = values[OFFICIAL_ATTEMPT]
    by_id = {str(attempt.id): attempt for attempt in found}
    by_points = _view().pick_official(
        [_entry(attempt, attempt.max_score or Decimal(0)) for attempt in found], rule
    )
    chosen = by_points  # within one revision percents order as points: no query for maxima
    if len({attempt.revision_id for attempt in found}) > 1:
        picked, _shown = _pick_by_percent(found, _maxima(run), rule)
        chosen = picked[0]
    attempt = by_id[chosen.attempt_id]
    figures = _average_figures(found, by_points) if rule == "average" else _figures_of(attempt)
    return Kept(attempt, figures, len(found), rule, _waits(rule, finished))


def pass_mark(run: QuizRun) -> Decimal | None:
    """The run's pass mark in percent, None when there is none."""
    mark = Decimal(of(run)[PASS_MARK])
    return mark if mark > 0 else None


def judge(score: Decimal, max_score: Decimal, mark: Decimal | None) -> bool | None:
    """Passed when the exact percent reaches the mark; None without a mark or a maximum."""
    if mark is None or max_score <= 0:
        return None
    return score / max_score * _HUNDRED >= mark


def attempt_passed(attempt: Attempt) -> bool | None:
    """Computed from the run's mark each time, never stored. None while unjudged."""
    if attempt.status != Attempt.Status.SUBMITTED or attempt.score is None:
        return None
    return judge(attempt.score, attempt.max_score or Decimal(0), pass_mark(attempt.run))


def kept_passed(found: Kept | None, run: QuizRun) -> bool | None:
    """The kept figures against the mark; None when nothing is kept or it waits for grading."""
    if found is None or found.waiting:
        return None
    return judge(found.figures.score, found.figures.max_score, pass_mark(run))


def official_attempt(participant: Participant) -> Attempt | None:
    """The attempt that counts for the participant; waiting attempts are ignored."""
    found = kept(participant)
    return None if found is None else found.attempt


def _entry(attempt: Attempt, max_score: Decimal) -> ScoreEntry:
    who = attempt.participant
    return ScoreEntry(
        key=_key(attempt),
        attempt_id=str(attempt.id),
        name=who.display_name if who else "",
        score=cast(Decimal, attempt.score),
        max_score=max_score,
        submitted_at=cast(datetime, attempt.submitted_at),
        duration_ms=attempt.duration_ms,
    )


def _rank(
    attempts: list[Attempt], max_score: Decimal, values: Mapping[str, str]
) -> list[RankedRow]:
    view = _view()
    groups: dict[str, list[ScoreEntry]] = {}
    for attempt in attempts:
        groups.setdefault(_key(attempt), []).append(_entry(attempt, max_score))
    official = [view.pick_official(found, values[OFFICIAL_ATTEMPT]) for found in groups.values()]
    return view.rank(official, values, values[SEED])


_SHARE = Decimal("0.000001")


def _share(entry: ScoreEntry) -> ScoreEntry:
    """The entry with its score as the percent of its own maximum, to rank and pick by."""
    score = (
        Decimal(0)
        if entry.max_score <= 0
        else (entry.score / entry.max_score * _HUNDRED).quantize(_SHARE, ROUND_HALF_UP)
    )
    return replace(entry, score=score, max_score=_HUNDRED)


def _pick_by_percent(
    attempts: list[Attempt], maxima: Mapping[object, Decimal], rule: str
) -> tuple[list[ScoreEntry], dict[str, ScoreEntry]]:
    """Each participant's counted entry as a percent, and the points it shows, by attempt id."""
    view = _view()
    groups: dict[str, list[ScoreEntry]] = {}
    for attempt in attempts:
        top = maxima.get(attempt.revision_id, attempt.max_score or Decimal(0))
        groups.setdefault(_key(attempt), []).append(_entry(attempt, top))
    official = []
    shown: dict[str, ScoreEntry] = {}
    for found in groups.values():
        chosen = view.pick_official([_share(entry) for entry in found], rule)
        official.append(chosen)
        if rule == "average":
            shown[chosen.attempt_id] = view.pick_official(found, rule)
        else:
            shown[chosen.attempt_id] = next(e for e in found if e.attempt_id == chosen.attempt_id)
    return official, shown


def _rank_by_percent(
    attempts: list[Attempt], maxima: Mapping[object, Decimal], values: Mapping[str, str]
) -> _Ranked:
    """All revisions in one table, each attempt measured against its own revision (ADR-0065)."""
    official, shown = _pick_by_percent(attempts, maxima, values[OFFICIAL_ATTEMPT])
    rows = _view().rank(official, values, values[SEED])
    return _Ranked(None, None, None, rows, by_percent=True, shown=shown)


def _maxima(run: QuizRun, used: list[RunRevision] | None = None) -> dict[object, Decimal]:
    """The maximum of each revision the run used, the newest row first."""
    if used is None:
        used = list(RunRevision.objects.filter(run=run).order_by("-active_from"))
    maxima: dict[object, Decimal] = {}
    for row in used:
        maxima.setdefault(row.revision_id, row.max_score)
    return maxima


def counted(run: QuizRun, attempts: Sequence[Attempt], mode: str | None = None) -> list[Attempt]:
    """The attempts the run's own revision mode counts: `latest` keeps its current revision.

    `mode` is the run's revision mode when the caller has already read it.
    """
    if (mode or revision_mode(run)) == LATEST:
        return [a for a in attempts if a.revision_id == run.current_revision_id]
    return list(attempts)


def _shown_candidates(run: QuizRun) -> list[Attempt]:
    """The run's candidates its own revision mode shows."""
    return counted(run, _candidates(run))


def _rank_shared(runs: list[QuizRun], values: Mapping[str, str]) -> _Ranked:
    """The runs of a shared board in one table by percent, with the main run's tie rules.

    Each run keeps its own revision mode and its own rule for the counted attempt; a participant
    belongs to one run, so the row keys never meet across runs.
    """
    official: list[ScoreEntry] = []
    shown: dict[str, ScoreEntry] = {}
    run_of: dict[str, int] = {}
    for run in runs:
        attempts = _shown_candidates(run)
        picked, points = _pick_by_percent(attempts, _maxima(run), of(run)[OFFICIAL_ATTEMPT])
        official += picked
        shown |= points
        run_of |= {entry.key: run.run_no or 0 for entry in picked}
    rows = _view().rank(official, values, values[SEED])
    return _Ranked(None, None, None, rows, by_percent=True, shown=shown, run_of=run_of)


def _ranked_tables(run: QuizRun, values: Mapping[str, str]) -> list[_Ranked]:
    attempts = _candidates(run)
    used = list(
        RunRevision.objects.filter(run=run).select_related("revision").order_by("-active_from")
    )
    mode = revision_mode(run)
    if mode == PERCENT:
        return [_rank_by_percent(attempts, _maxima(run, used), values)]
    if mode == LATEST:
        current = next((row for row in used if row.revision_id == run.current_revision_id), None)
        top = current.max_score if current else run.current_revision.max_score
        mine = counted(run, attempts, mode)
        return [
            _Ranked(
                run.current_revision_id,
                run.current_revision.revision_no,
                top,
                _rank(mine, top, values),
            )
        ]
    tables: list[_Ranked] = []
    seen: set[object] = set()
    for row in used:
        if row.revision_id in seen:
            continue
        seen.add(row.revision_id)
        mine = [a for a in attempts if a.revision_id == row.revision_id]
        tables.append(
            _Ranked(
                row.revision_id,
                row.revision.revision_no,
                row.max_score,
                _rank(mine, row.max_score, values),
            )
        )
    return tables


def _percent(score: Decimal, max_score: Decimal) -> int:
    if max_score <= 0:
        return 0
    return int((score / max_score * _HUNDRED).quantize(Decimal(1), ROUND_HALF_UP))


def _run_label(locale: str, run_no: int, label: str) -> str:
    with translation.override(locale):
        return gettext("Run %(no)s · %(label)s") % {"no": run_no, "label": label}


def _build(
    run: QuizRun, audience: Literal["public", "admin"], locale: str, *, own_run: bool = False
) -> Board:
    """The run's board; a main run shows the rows of its whole shared board (ADR-0065).

    `own_run` leaves the shared board out, for what is the run's own data, such as its export.

    Visibility, columns, live names and unnamed rows follow the main run; pending grading in
    any linked run holds the board, and it is final only when every linked run ended. Publicly,
    a member whose own board is hidden as archived or deleted adds no rows; the admin sees them.
    """
    values = of(run)
    linked_runs = [run] if own_run else shared_runs(run)
    runs = linked_runs
    pending = any(_pending(linked) for linked in runs)
    columns = _columns(run, values)
    ended = all(linked.status in _ENDED for linked in runs)
    # A hidden board may still be turned on after the end, so pages keep asking.
    final = ended and not pending and values[SCOREBOARD_VISIBILITY] != "hidden"
    hidden = None if audience == "admin" else _hidden(run, values, pending)
    if hidden is not None:
        return Board([], hidden, columns, final)
    public = audience == "public"
    if public:  # a member whose own board is archived or deleted keeps its rows to itself
        runs = [
            linked
            for linked in runs
            if linked == run
            or _hidden(linked, of(linked), False) not in ("archived", "data_deleted")
        ]
    numbers: dict[str, int] = {}
    for linked in runs:
        numbers |= _numbers(linked)  # keys are participant or attempt ids, never shared by runs
    mark = pass_mark(run)
    anonymise = (
        public
        and any(linked.status == QuizRun.Status.OPEN for linked in runs)
        and values[SCOREBOARD_LIVE_NAMES] == "anonymised"
    )
    unlisted = public and values[SCOREBOARD_UNNAMED] == "unlisted"
    tables = []
    # Still one table by percent when only the main run is left to show publicly.
    shared = len(linked_runs) > 1
    rankings = [_rank_shared(runs, values)] if shared else _ranked_tables(run, values)
    for ranked in rankings:
        rows = []
        for item in ranked.rows:
            entry = item.entry
            if ranked.by_percent:  # the entry holds the percent, `shown` the points
                points = cast(Mapping[str, ScoreEntry], ranked.shown)[entry.attempt_id]
                percent = int(entry.score.quantize(Decimal(1), ROUND_HALF_UP))
            else:
                points = entry
                percent = _percent(entry.score, entry.max_score)
            named = bool(entry.name) and not anonymise
            if named:
                label = entry.name
            elif unlisted and not entry.name:
                continue
            else:
                label = anonymous_label(run.quiz, locale, numbers.get(entry.key, 0))
            # Anonymous labels repeat across runs; the admin also sees the run of a named row.
            if ranked.run_of is not None and (not named or not public):
                label = _run_label(locale, ranked.run_of[entry.key], label)
            rows.append(
                BoardRow(
                    rank=item.rank,
                    label=label,
                    score=points.score,
                    max_score=points.max_score,
                    percent=percent,
                    submitted_at=entry.submitted_at,
                    duration_ms=entry.duration_ms,
                    mine=False,
                    key=entry.key,
                    attempt_id=entry.attempt_id,
                    passed=judge(points.score, points.max_score, mark),
                )
            )
        tables.append(Table(ranked.revision_no, ranked.max_score, rows))
    return Board(tables, None, columns, final)


def board(
    run: QuizRun,
    *,
    audience: Literal["public", "admin"],
    locale: str,
    viewer: Participant | None = None,
    own_run: bool = False,
) -> Board:
    """The admin sees every board with names. A public one is cached for a few seconds.

    `own_run` ranks only the run's own rows even on a shared main run; never cached.
    """
    if audience == "admin" or own_run:
        found = _build(run, audience, locale, own_run=own_run)
    else:
        cache_key = _cache_key(run, locale)
        found = cache.get(cache_key)
        if found is None:
            found = _build(run, audience, locale)
            cache.set(cache_key, found, BOARD_CACHE_SECONDS)
    if viewer is None:
        return found
    mine = str(viewer.id)
    return replace(
        found,
        tables=[
            replace(table, rows=[replace(row, mine=row.key == mine) for row in table.rows])
            for table in found.tables
        ],
    )


# Shared board of several runs (ADR-0065) ---------------------------------------------------

TOO_FEW = "too_few"
OTHER_QUIZ = "other_quiz"
ALREADY_SHARED = "already_shared"
MAIN_IS_MEMBER = "main_is_member"


class ShareRefused(Exception):
    """Runs that cannot share a board; `code` says why (the codes above, or `test_run`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def shared_runs(main: QuizRun) -> list[QuizRun]:
    """The main run and the runs it shows on its board, by run number; `[main]` when none."""
    if main.kind == QuizRun.Kind.TEST:
        return [main]
    members = list(
        QuizRun.objects.filter(board_main=main).select_related("quiz", "current_revision")
    )
    if not members:
        return [main]
    return sorted([main, *members], key=lambda linked: linked.run_no or 0)


def shared_numbers(run: QuizRun) -> list[int]:
    """The run numbers on a main run's shared board; empty for a run that shows only itself."""
    if run.board_main_id is not None:
        return []
    linked = shared_runs(run)
    return [r.run_no or 0 for r in linked] if len(linked) > 1 else []


def _refusal(main: QuizRun, members: list[QuizRun]) -> str | None:
    if main.kind == QuizRun.Kind.TEST or any(m.kind == QuizRun.Kind.TEST for m in members):
        return TEST_RUN
    if any(m.quiz_id != main.quiz_id for m in members):
        return OTHER_QUIZ
    if not members:
        return TOO_FEW
    if main.board_main_id is not None:
        return MAIN_IS_MEMBER
    if any(m.board_main_id not in (None, main.pk) for m in members):
        return ALREADY_SHARED
    if QuizRun.all_kinds.filter(board_main__in=members).exists():
        return ALREADY_SHARED
    return None


def _forget_all(run_ids: set[object]) -> None:
    for found in QuizRun.all_kinds.select_related("quiz", "current_revision").filter(
        pk__in=run_ids
    ):
        _forget(found)


def share_board(main: QuizRun, members: Sequence[QuizRun], *, admin_id: str) -> None:
    """Shows the members' rows on the main run's public board; nothing else moves.

    The given members replace the main run's earlier ones; a run left out is on its own again.
    Raises `ShareRefused`, or `authoring.QuizArchived` for an archived quiz.
    """
    authoring.ensure_editable(main.quiz)
    with transaction.atomic():
        current = QuizRun.all_kinds.select_for_update().filter(pk=main.pk).first()
        if current is None:
            raise ShareRefused(TOO_FEW)
        wanted = {m.pk for m in members} - {current.pk}
        found = list(QuizRun.all_kinds.filter(pk__in=wanted).order_by("run_no"))
        code = _refusal(current, found) if len(found) == len(wanted) else TOO_FEW
        if code is not None:
            raise ShareRefused(code)
        before = set(QuizRun.all_kinds.filter(board_main=current).values_list("pk", flat=True))
        QuizRun.all_kinds.filter(board_main=current).exclude(pk__in=wanted).update(board_main=None)
        QuizRun.all_kinds.filter(pk__in=wanted).update(board_main=current)
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.board_combined",
            entity_type="run",
            entity_id=str(current.id),
            details={"main": current.run_no, "members": [m.run_no for m in found]},
        )
    _forget_all({current.pk} | before | wanted)


def split_board(main: QuizRun, *, admin_id: str) -> None:
    """Every run of the main run's shared board shows only its own board again."""
    authoring.ensure_editable(main.quiz)
    with transaction.atomic():
        members = list(QuizRun.all_kinds.filter(board_main=main).order_by("run_no"))
        if not members:
            return
        QuizRun.all_kinds.filter(board_main=main).update(board_main=None)
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.board_split",
            entity_type="run",
            entity_id=str(main.id),
            details={"main": main.run_no, "members": [m.run_no for m in members]},
        )
    _forget_all({main.pk} | {m.pk for m in members})


def place_of(attempt: Attempt) -> tuple[int, int] | None:
    """The place of the attempt's participant and of how many, uncached, counting the unlisted."""
    run = attempt.run
    values = of(run)
    if _hidden(run, values, _pending(run)) is not None:
        return None
    key = _key(attempt)
    for ranked in _ranked_tables(run, values):
        if ranked.revision_id is not None and ranked.revision_id != attempt.revision_id:
            continue
        for item in ranked.rows:
            if item.entry.key == key:
                return item.rank, len(ranked.rows)
    return None
