"""Scoreboard settings fixed on the run, and the board built from submitted attempts (C4).

The rules of order live in the `result_view` module; this module reads attempts and decides who
may see what (ADR-0026, ADR-0031, ADR-0051).
"""

import heapq
import secrets
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, cast

from django.core.cache import cache
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext

from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
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
    RankedRow,
    ResultViewPlugin,
    ScoreEntry,
)
from app.domain import data_policy, settings
from app.domain.models import Attempt, Participant, Quiz, QuizRun, RunRevision
from app.kernel import audit, registry

__all__ = [
    "BOARD_CACHE_SECONDS",
    "Board",
    "BoardRow",
    "MergeRefused",
    "ResultConflict",
    "Table",
    "board",
    "is_public",
    "merge",
    "place_of",
    "unmerge",
    "anonymous_label",
    "conflicts",
    "ensure_run_allowed",
    "needs_participant",
    "reasons",
    "of",
    "official_attempt",
    "participant_numbers",
    "revision_mode",
    "rules_for_quiz",
    "set_display",
    "snapshot",
]

SEED = "seed"
MERGED = "merged"
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
    if (run.results_json or {}).get(MERGED) == "on":
        return MERGED
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
    """Only what changes what is shown; the rest decides the order and stays as opened."""
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


@dataclass(frozen=True)
class Table:
    revision_no: int | None
    max_score: Decimal
    rows: list[BoardRow]


@dataclass(frozen=True)
class Board:
    tables: list[Table]
    hidden: str | None  # "hidden", "after_end", "pending", "archived"
    columns: tuple[str, ...]
    final: bool  # nothing on it can change any more


@dataclass(frozen=True)
class _Ranked:
    revision_id: object | None  # None for one table over all revisions
    revision_no: int | None
    max_score: Decimal
    rows: list[RankedRow]


class MergeRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _cache_key(run: QuizRun, locale: str) -> str:
    return f"kvz-board:{run.id}:{locale}"


def _forget(run: QuizRun) -> None:
    """A changed board is shown at once, so a hidden one does not stay public for seconds."""
    locales = set(run.quiz.supported_locales) | set(
        run.current_revision.snapshot_json.get("locales", [])
    )
    cache.delete_many([_cache_key(run, locale) for locale in locales])


def _view() -> ResultViewPlugin:
    return cast(ResultViewPlugin, registry.get("result_view", "local"))


def _pending(run: QuizRun) -> bool:
    return Attempt.objects.filter(run=run, status=Attempt.Status.PENDING_GRADING).exists()


def _hidden(run: QuizRun, values: Mapping[str, str], pending: bool) -> str | None:
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


def is_public(run: QuizRun) -> bool:
    return _hidden(run, of(run), _pending(run)) is None


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
    """Every browser and every attempt without one, in the order they came, so a number stays."""
    people = (
        (who.created_at, str(who.id), str(who.id))
        for who in Participant.objects.filter(run=run).order_by("created_at", "id")
    )
    loose = (
        (attempt.started_at, str(attempt.id), f"a:{attempt.id}")
        for attempt in Attempt.objects.filter(run=run, participant__isnull=True).order_by(
            "started_at", "id"
        )
    )
    merged: Iterator[tuple[datetime, str, str]] = heapq.merge(people, loose)
    return {key: number for number, (_when, _id, key) in enumerate(merged, start=1)}


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


def official_attempt(participant: Participant) -> Attempt | None:
    """The attempt that counts for the participant, by the run's rule (best or first).

    Only submitted attempts with a score: switched, abandoned, unsent and waiting ones never count.
    Each attempt is measured against its own maximum, as rewards measure it.
    """
    found = list(
        Attempt.objects.filter(
            participant=participant,
            status=Attempt.Status.SUBMITTED,
            submitted_at__isnull=False,
            score__isnull=False,
        )
    )
    if not found:
        return None
    for attempt in found:
        attempt.participant = participant  # one query, not one per attempt
    by_id = {str(attempt.id): attempt for attempt in found}
    entries = [_entry(attempt, attempt.max_score or Decimal(0)) for attempt in found]
    chosen = _view().pick_official(entries, of(participant.run)[OFFICIAL_ATTEMPT])
    return by_id[chosen.attempt_id]


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


def _ranked_tables(run: QuizRun, values: Mapping[str, str]) -> list[_Ranked]:
    attempts = _candidates(run)
    used = list(
        RunRevision.objects.filter(run=run).select_related("revision").order_by("-active_from")
    )
    mode = revision_mode(run)
    if mode == MERGED and len({row.max_score for row in used}) > 1:
        mode = "separate"  # a later revision changed the maximum, so one table would mislead
    if mode == MERGED:
        top = used[0].max_score if used else run.current_revision.max_score
        return [_Ranked(None, None, top, _rank(attempts, top, values))]
    if mode == "latest":
        current = next((row for row in used if row.revision_id == run.current_revision_id), None)
        top = current.max_score if current else run.current_revision.max_score
        mine = [a for a in attempts if a.revision_id == run.current_revision_id]
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


def _build(run: QuizRun, audience: Literal["public", "admin"], locale: str) -> Board:
    values = of(run)
    pending = _pending(run)
    columns = _columns(run, values)
    # A hidden board may still be turned on after the end, so pages keep asking.
    final = run.status in _ENDED and not pending and values[SCOREBOARD_VISIBILITY] != "hidden"
    hidden = None if audience == "admin" else _hidden(run, values, pending)
    if hidden is not None:
        return Board([], hidden, columns, final)
    numbers = _numbers(run)
    public = audience == "public"
    anonymise = (
        public
        and run.status == QuizRun.Status.OPEN
        and values[SCOREBOARD_LIVE_NAMES] == "anonymised"
    )
    unlisted = public and values[SCOREBOARD_UNNAMED] == "unlisted"
    tables = []
    for ranked in _ranked_tables(run, values):
        rows = []
        for item in ranked.rows:
            entry = item.entry
            if entry.name and not anonymise:
                label = entry.name
            elif unlisted and not entry.name:
                continue
            else:
                label = anonymous_label(run.quiz, locale, numbers.get(entry.key, 0))
            rows.append(
                BoardRow(
                    rank=item.rank,
                    label=label,
                    score=entry.score,
                    max_score=ranked.max_score,
                    percent=_percent(entry.score, ranked.max_score),
                    submitted_at=entry.submitted_at,
                    duration_ms=entry.duration_ms,
                    mine=False,
                    key=entry.key,
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
) -> Board:
    """The admin sees every board with names. A public one is cached for a few seconds."""
    if audience == "admin":
        found = _build(run, audience, locale)
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


def _set_merged(run: QuizRun, value: str | None, action: str, admin_id: str) -> None:
    with transaction.atomic():
        current = QuizRun.objects.select_for_update().get(pk=run.pk)
        stored = dict(current.results_json or {})
        if value is None:
            stored.pop(MERGED, None)
        else:
            stored[MERGED] = value
        current.results_json = stored
        current.save(update_fields=["results_json"])
        _forget(current)  # a rollback only costs a rebuilt board
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action=action,
            entity_type="run",
            entity_id=str(run.id),
        )
    run.results_json = current.results_json


def merge(run: QuizRun, *, admin_id: str) -> None:
    """One table for all revisions, only with equal maximum points (AC-06, ADR-0008)."""
    used = RunRevision.objects.filter(run=run)
    if used.values("revision_id").distinct().count() < 2:
        raise MergeRefused("one_revision")
    if used.values("max_score").distinct().count() > 1:
        raise MergeRefused("max_differs")
    _set_merged(run, "on", "run.revisions_merged", admin_id)


def unmerge(run: QuizRun, *, admin_id: str) -> None:
    _set_merged(run, None, "run.revisions_unmerged", admin_id)
