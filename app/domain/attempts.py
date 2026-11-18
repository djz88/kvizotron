"""Starting and submitting attempts. The server alone decides score and times (ADR-0009)."""

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F
from django.utils import timezone

from app.contracts import (
    JSON,
    LOCAL_RESUME,
    PHOTO_PUBLIC,
    REPEAT_ATTEMPTS,
    QuestionTypePlugin,
    ScoreBreakdown,
    ScoringStrategyPlugin,
)
from app.domain import clock, data_policy, participants, run_flow, selection, settings, tokens
from app.domain import questions as question_rules
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Participant,
    QuizRevision,
    QuizRun,
    RunRevision,
)
from app.kernel import events, registry

# The token outlives any limit or deadline, which `_check_still_valid` enforces on its own.
ATTEMPT_LIFETIME = timedelta(hours=24)
# A photo sent as a run ends still gets a real answer, and answers shown after the run closes wait
# this long, so that the last attempts are in before anyone sees the solutions.
LATE_UPLOAD_WINDOW = timedelta(minutes=10)
DEFAULT_FLOW: dict[str, Any] = {
    "navigation": settings.Navigation.ALL_AT_ONCE.value,
    "moment": settings.RevealMoment.NEVER.value,
    "level": settings.RevealLevel.VERDICT.value,
    "shuffle_questions": False,
}


class AttemptError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StartedAttempt:
    attempt: Attempt
    token: str
    submission_key: str


@dataclass(frozen=True)
class AttemptResult:
    earned_points: Decimal
    max_points: Decimal
    correct_count: int | None
    pending: bool = False  # earned is what the server gave; a person decides the rest

    @property
    def percentage(self) -> Fraction:
        """Exact, for any comparison. Round only for display (FR-25)."""
        if not self.max_points:
            return Fraction(0)
        return Fraction(self.earned_points) / Fraction(self.max_points) * 100

    @property
    def percentage_display(self) -> float:
        return round(float(self.percentage), 2)


@dataclass(frozen=True)
class _AnswerRow:
    question_id: str
    answer: JSON
    auto_points: Decimal
    manual_max: Decimal
    asset_id: str | None


@dataclass(frozen=True)
class SwitchedAttempt:
    started: StartedAttempt
    answers: dict[str, JSON]  # answers that stay, by question id
    changed: set[str]  # questions marked as changed


def with_retry[T](function: Callable[[], T], tries: int = 3, base_delay: float = 0.05) -> T:
    """Repeat a short transaction when SQLite reports a lock."""
    for attempt in range(tries):
        try:
            return function()
        except OperationalError as exc:
            if "locked" not in str(exc) or attempt == tries - 1:
                raise
            time.sleep(base_delay * 2**attempt)
    raise AssertionError("unreachable")


def manifest_hash(question_ids: Sequence[str]) -> str:
    """Identifies what the participant was given: the questions and their order."""
    return hashlib.sha256(",".join(question_ids).encode()).hexdigest()


def items_of(attempt: Attempt) -> list[selection.Item]:
    """The questions fixed at start. An attempt older than that gets all of them."""
    if attempt.selection_json:
        return attempt.selection_json["items"]
    return selection.own_items(attempt.revision.snapshot_json)


def questions_of(attempt: Attempt) -> list[dict[str, Any]]:
    return selection.given(attempt.revision.snapshot_json, items_of(attempt))


def flow_of(attempt: Attempt) -> dict[str, Any]:
    """Behaviour fixed at start, so a settings change reaches only new attempts."""
    return DEFAULT_FLOW | (attempt.settings_json or {})  # an older attempt may lack a key


def option_seed(attempt: Attempt) -> str | None:
    return (attempt.selection_json or {}).get("seed")


def option_seed_for(attempt: Attempt, question: Mapping[str, Any]) -> str | None:
    """The attempt froze the quiz's value as its seed. A question may decide for itself."""
    seed = option_seed(attempt)
    own = settings.question_value(settings.SHUFFLE_OPTIONS, question)
    if own is None:
        return seed
    return (seed or _question_seed(attempt)) if own == settings.Switch.ON else None


def _question_seed(attempt: Attempt) -> str:
    """For a question shuffling on its own. It outlives a switch, so the order stays."""
    return (attempt.selection_json or {}).get("question_seed") or str(attempt.pk)


def _require_modules(revision: QuizRevision) -> None:
    """Before anything is stored: an attempt that cannot be shown must not exist."""
    try:
        for question in selection.all_questions(revision.snapshot_json):
            registry.get("question_type", question["type"], include_disabled=True)
            registry.get("scoring_strategy", question["scoring"], include_disabled=True)
    except registry.UnknownPort as exc:
        raise AttemptError("revision_unavailable") from exc


def _check_test_link(run: QuizRun, now: datetime) -> None:
    """The tester sees why the page stopped working, also on a page that was already open."""
    if run.kind == QuizRun.Kind.TEST and not run.test_link.is_playable(now):
        raise AttemptError("test_link_ended")


def limit_for(run: QuizRun) -> int | None:
    """A test run has no plan, so it follows the quiz as it is now."""
    if run.kind == QuizRun.Kind.TEST:
        return settings.attempt_limit_seconds(run.quiz)
    return run.attempt_limit_sec


def ends_at(attempt: Attempt) -> datetime | None:
    """`min(deadline_at, started_at + limit)` (FR-11). The deadline can move, the limit cannot."""
    limit = flow_of(attempt).get("limit_sec")
    own = attempt.started_at + timedelta(seconds=limit) if limit else None
    return min((end for end in (attempt.run.deadline_at, own) if end is not None), default=None)


def time_left(attempt: Attempt) -> int | None:
    """Whole seconds to show. None when no time applies, 0 when it is over."""
    if attempt.run.status != QuizRun.Status.OPEN:
        return 0
    ends = ends_at(attempt)
    if ends is None:
        return None
    return max(0, int((ends - timezone.now()).total_seconds()))


def remaining(attempt_id: UUID, token: str) -> int | None:
    """What an open page asks every 30 s. None when nothing is left to count down."""
    claims = _verify(token, attempt_id)
    attempt = _load_for(claims)
    _check_claims(attempt, claims)
    return time_left(attempt) if attempt.status == Attempt.Status.IN_PROGRESS else None


def start(
    run: QuizRun, *, participant: Participant | None = None, unlocked: bool = True
) -> StartedAttempt:
    """What the run's rules say about this participant is decided in the transaction that acts.

    `unlocked` says the caller holds proof of the run's access code. A test run has no code.
    """
    return with_retry(lambda: _start(run, participant, unlocked))


def _start(run: QuizRun, participant: Participant | None, unlocked: bool) -> StartedAttempt:
    with transaction.atomic():  # IMMEDIATE: a second tab waits and sees the first one's attempt
        return _begin_attempt(run, participant, unlocked)


def _begin_attempt(run: QuizRun, participant: Participant | None, unlocked: bool) -> StartedAttempt:
    now = timezone.now()
    _check_test_link(run, now)
    if run.status == QuizRun.Status.SCHEDULED:
        raise AttemptError("run_not_started")
    if run.status != QuizRun.Status.OPEN or _past(now, run.deadline_at):
        raise AttemptError("run_closed")
    begun = participants.begin(run, participant)
    locked = bool(run.access_code_hash) and not unlocked and run.kind != QuizRun.Kind.TEST
    if locked and not (begun.decision == "resume" and begun.attempt is not None):
        raise AttemptError("code_required")  # only an attempt already begun carries on
    if begun.decision == "played":
        raise AttemptError("already_played")
    if begun.decision == "time_up":
        raise AttemptError("time_is_up")
    if begun.decision == "resume" and begun.attempt is not None:
        return resume(begun.attempt)
    if begun.decision == "replace" and begun.attempt is not None:
        Attempt.objects.filter(pk=begun.attempt.pk, status=Attempt.Status.IN_PROGRESS).update(
            status=Attempt.Status.ABANDONED
        )
    revision = run.current_revision
    _require_modules(revision)
    flow = run_flow.flow(run)
    attempt = Attempt(
        run=run,
        participant=participant,
        revision=revision,
        selection_json={
            "items": selection.choose(revision.snapshot_json, flow.shuffle_questions),
            "seed": secrets.token_urlsafe(8) if flow.shuffle_options else None,
        },
        settings_json={
            "navigation": flow.navigation,
            "moment": flow.moment,
            "level": flow.level,
            "shuffle_questions": flow.shuffle_questions,
            "page_size": flow.page_size,
            "profile": effective_profile(run),
            "limit_sec": limit_for(run),
            LOCAL_RESUME: settings.resolve(LOCAL_RESUME, run.quiz),
        },
    )
    attempt.settings_json["told_public"] = _told_public(attempt)
    attempt.save()
    token = _issue(attempt, attempt.started_at + ATTEMPT_LIFETIME)
    return StartedAttempt(attempt, token, secrets.token_urlsafe(16))


def effective_profile(run: QuizRun) -> str:
    """What an attempt of this run keeps. One answer for freezing at start and for "gone".

    A test link follows the quiz as it is now, except that a photo cannot be kept statelessly.
    """
    profile = data_policy.of(run)[data_policy.PROFILE]
    if (
        run.kind == QuizRun.Kind.TEST
        and data_policy.is_stateless(profile)
        and data_policy.has_photo_question(run.current_revision.snapshot_json)
    ):
        return settings.DataProfile.SCORE.value
    return profile


def resume(attempt: Attempt) -> StartedAttempt:
    """The same attempt, questions and time, with a token and a submission key that work now."""
    token = _issue(attempt, attempt.started_at + ATTEMPT_LIFETIME)
    return StartedAttempt(attempt, token, secrets.token_urlsafe(16))


COPY_LIFETIME = timedelta(hours=24)


def copy_expiry(attempt: Attempt) -> datetime:
    """When the browser's copy of an unsubmitted attempt must be gone: its end, else 24 h."""
    latest = attempt.started_at + COPY_LIFETIME
    end = ends_at(attempt)
    return min(latest, end) if end is not None else latest


def resume_by_token(run: QuizRun, attempt_id: UUID, token: str) -> StartedAttempt:
    """The attempt a browser kept a copy of, as long as it is still open and may carry on.

    Needs no access code: a changed code still lets a running attempt carry on (ADR-0049).
    """
    claims = _verify(token, attempt_id)
    if claims.run_id != run.id:
        raise AttemptError("not_in_run")
    return with_retry(lambda: _resume_by_token(claims))


def _resume_by_token(claims: tokens.AttemptClaims) -> StartedAttempt:
    with transaction.atomic():
        attempt = _load_for(claims)
        _check_claims(attempt, claims)
        current = attempt
        while current.replaced_by_id is not None:
            current = _load(current.replaced_by_id)
        if current.status == Attempt.Status.ABANDONED:
            raise AttemptError("attempt_closed")
        if current.status in Attempt.FINISHED:
            raise AttemptError("already_submitted")
        _check_still_valid(current, claims, timezone.now())
        if current.run.status != QuizRun.Status.OPEN:
            raise AttemptError("run_closed")  # a closed run takes no new page, only a late send
        if flow_of(current).get(LOCAL_RESUME) != "on":
            raise AttemptError("resume_off")
        return resume(current)


def _told_public(attempt: Attempt) -> list[str]:
    """Photo questions whose page warns that a photo may become public. Nothing else ever can."""
    return [
        question["id"]
        for question in questions_of(attempt)
        if file_fields(question)
        and settings.photo_level(attempt.run.quiz, question) == PHOTO_PUBLIC
    ]


def _issue(attempt: Attempt, expires_at: datetime) -> str:
    return tokens.issue(
        tokens.AttemptClaims(
            run_id=attempt.run_id,
            revision_id=attempt.revision_id,
            attempt_id=attempt.id,
            started_at=attempt.started_at,
            expires_at=expires_at,
            manifest_hash=manifest_hash([item["id"] for item in items_of(attempt)]),
        )
    )


def submit(
    attempt_id: UUID,
    token: str,
    answers: Mapping[str, JSON],
    submission_key: str,
    received_at: datetime | None = None,
    lenient: bool = False,
    identity: participants.Identity | None = None,
) -> AttemptResult:
    """`received_at` is when the request arrived: that time counts, not when storing ends.

    `lenient` is for the automatic submission when time runs out, as a half-filled answer must not
    cost the whole attempt. An answer that cannot be read counts as unanswered, so it gains nothing.
    The same goes for a name that is taken: it is left out and the score stays.
    """
    claims = _verify(token, attempt_id)
    attempt = _load_for(claims)
    _check_claims(attempt, claims)
    if attempt.status == Attempt.Status.ABANDONED:
        raise AttemptError("attempt_closed")
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return _stored_result(attempt, submission_key)
    now = received_at or timezone.now()
    _check_still_valid(attempt, claims, now)
    result, rows = _score(attempt, answers, lenient)
    stored = with_retry(
        lambda: _store(attempt, result, rows, submission_key, now, identity, lenient)
    )
    return result if stored else _stored_result(_load_for(claims), submission_key)


def verify_open(attempt_id: UUID, token: str, received_at: datetime | None = None) -> None:
    """What a submission will need, for what must happen before it, such as storing a photo."""
    claims = _verify(token, attempt_id)
    attempt = _load_for(claims)
    _check_claims(attempt, claims)
    if attempt.status == Attempt.Status.ABANDONED:
        raise AttemptError("attempt_closed")
    _check_still_valid(attempt, claims, received_at or timezone.now())


def check(attempt_id: UUID, token: str, question_id: str) -> tuple[Mapping[str, Any], str]:
    """The question and level to show, when this attempt may see a solution now (ADR-0035).

    Stores nothing. The final submission is still what counts.
    """
    claims = _verify(token, attempt_id)
    attempt = _load_for(claims)
    _check_claims(attempt, claims)
    if attempt.status == Attempt.Status.SWITCHED:
        raise AttemptError("attempt_switched")
    if attempt.status != Attempt.Status.IN_PROGRESS:
        raise AttemptError("already_submitted")
    _check_still_valid(attempt, claims, timezone.now())
    flow = flow_of(attempt)
    if flow["moment"] != settings.RevealMoment.AFTER_EACH:
        raise AttemptError("reveal_not_allowed")
    for question in questions_of(attempt):
        if question["id"] == question_id:
            return question, flow["level"]
    raise AttemptError("not_in_attempt")


def must_switch(attempt: Attempt) -> bool:
    """A page rule, not a boundary: the old attempt can be submitted until it is switched."""
    if attempt.status == Attempt.Status.SWITCHED:
        return True
    run = attempt.run
    if attempt.status != Attempt.Status.IN_PROGRESS or run.status != QuizRun.Status.OPEN:
        return False
    return (
        attempt.revision_id != run.current_revision_id
        and run.current_row().switch_mode == RunRevision.SwitchMode.SWITCH
    )


def switch(attempt_id: UUID, token: str, answers: Mapping[str, JSON]) -> SwitchedAttempt:
    """Move to the round's current revision. Start time stays, so switching buys no time.

    On the current revision nothing changes, but a new token and submission key are still issued,
    so a repeated or late request gets a working form.
    """
    claims = _verify(token, attempt_id)
    return with_retry(lambda: _switch(attempt_id, claims, answers))


def _switch(
    attempt_id: UUID, claims: tokens.AttemptClaims, answers: Mapping[str, JSON]
) -> SwitchedAttempt:
    with transaction.atomic():  # IMMEDIATE, so a repeated request sees the first one's result
        attempt = _load_for(claims)
        _check_claims(attempt, claims)
        current = attempt
        while current.replaced_by_id is not None:
            current = _load(current.replaced_by_id)
        if current.status == Attempt.Status.ABANDONED:
            raise AttemptError("attempt_closed")
        if current.status in Attempt.FINISHED:
            raise AttemptError("already_submitted")
        _check_still_valid(current, claims, timezone.now())
        replacement = _replacement(current)
        kept, changed = _moved_answers(questions_of(attempt), questions_of(replacement), answers)
    token = _issue(replacement, claims.expires_at)
    return SwitchedAttempt(
        StartedAttempt(replacement, token, secrets.token_urlsafe(16)), kept, changed
    )


def _replacement(attempt: Attempt) -> Attempt:
    run = attempt.run
    if attempt.revision_id == run.current_revision_id:
        return attempt
    _require_modules(run.current_revision)
    flow = flow_of(attempt)
    replacement = Attempt.objects.create(
        run=run,
        participant_id=attempt.participant_id,
        revision=run.current_revision,
        selection_json={
            "items": selection.carry_over(
                attempt.revision.snapshot_json,
                items_of(attempt),
                run.current_revision.snapshot_json,
                bool(flow.get("shuffle_questions")),
            ),
            "seed": option_seed(attempt),
            "question_seed": _question_seed(attempt),
        },
        settings_json=flow,
    )
    Attempt.objects.filter(pk=replacement.pk).update(started_at=attempt.started_at)
    replacement.started_at = attempt.started_at
    Attempt.objects.filter(pk=attempt.pk).update(
        status=Attempt.Status.SWITCHED, replaced_by=replacement
    )
    return _load(replacement.id)


def _moved_answers(
    old: Sequence[Mapping[str, Any]],
    new: Sequence[Mapping[str, Any]],
    answers: Mapping[str, JSON],
) -> tuple[dict[str, JSON], set[str]]:
    """An answer stays when the question is the same; points and scoring may differ."""
    previous = {question["id"]: question for question in old}
    kept: dict[str, JSON] = {}
    changed: set[str] = set()
    for question in new:
        before = previous.get(question["id"])
        if before is None:
            continue
        if (before["type"], before["definition"]) != (question["type"], question["definition"]):
            changed.add(question["id"])
        elif question["id"] in answers and _is_valid(question, answers[question["id"]]):
            kept[question["id"]] = answers[question["id"]]
    return kept, changed


def _is_valid(question: Mapping[str, Any], answer: JSON) -> bool:
    plugin = cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )
    try:
        plugin.validate_submission(question["definition"], answer)
    except ValueError:
        return False
    return True


def _check_claims(attempt: Attempt, claims: tokens.AttemptClaims) -> None:
    if (
        attempt.run_id != claims.run_id
        or attempt.revision_id != claims.revision_id
        or manifest_hash([item["id"] for item in items_of(attempt)]) != claims.manifest_hash
    ):
        raise AttemptError("invalid_token")
    if attempt.status == Attempt.Status.ABANDONED:  # every token-based entry stops here
        raise AttemptError("attempt_closed")


def _past(now: datetime, end: datetime | None) -> bool:
    """Compared in whole seconds, so the boundary second still counts (ADR-0025)."""
    return end is not None and clock.whole_second(now) > clock.whole_second(end)


def _check_still_valid(attempt: Attempt, claims: tokens.AttemptClaims, now: datetime) -> None:
    run = attempt.run
    _check_test_link(run, now)
    if _past(now, claims.expires_at) or _past(now, ends_at(attempt)):
        raise AttemptError("attempt_expired")
    if run.status == QuizRun.Status.OPEN or (run.deadline_at and run.closed_at == run.deadline_at):
        return  # closing at the deadline must not refuse what arrived within it
    if run.closed_at is None or now > run.closed_at:
        raise AttemptError("run_closed")


def _verify(token: str, attempt_id: UUID) -> tokens.AttemptClaims:
    try:
        claims = tokens.verify(token)
    except tokens.InvalidToken as exc:
        raise AttemptError("invalid_token") from exc
    if claims.attempt_id != attempt_id:
        raise AttemptError("invalid_token")
    return claims


def _load(attempt_id: UUID) -> Attempt:
    try:
        return Attempt.objects.select_related("run", "run__current_revision", "revision").get(
            pk=attempt_id
        )
    except Attempt.DoesNotExist as exc:
        raise AttemptError("not_found") from exc


def _load_for(claims: tokens.AttemptClaims) -> Attempt:
    """A valid token whose row is gone: after a stateless submission that is the normal answer."""
    try:
        return _load(claims.attempt_id)
    except AttemptError as error:
        if error.code == "not_found" and _is_stateless_run(claims.run_id):
            raise AttemptError("attempt_gone") from error
        raise


def _is_stateless_run(run_id: UUID) -> bool:
    run = QuizRun.all_kinds.select_related("quiz", "current_revision").filter(pk=run_id).first()
    return run is not None and data_policy.is_stateless(effective_profile(run))


def missing_code(attempt_id: UUID, token: str) -> str:
    """What to say about an attempt id with no row: gone only if the token proves it existed."""
    try:
        claims = tokens.verify(token)
    except tokens.InvalidToken:
        return "not_found"
    if claims.attempt_id == attempt_id and _is_stateless_run(claims.run_id):
        return "attempt_gone"
    return "not_found"


def _stored_result(attempt: Attempt, submission_key: str) -> AttemptResult:
    if attempt.status == Attempt.Status.ABANDONED:  # closed after the checks, before storing
        raise AttemptError("attempt_closed")
    if attempt.status == Attempt.Status.SWITCHED:
        raise AttemptError("attempt_switched")
    if attempt.submission_key != submission_key:
        raise AttemptError("already_submitted")
    return AttemptResult(
        Decimal(attempt.score or 0),
        Decimal(attempt.max_score or 0),
        attempt.correct_count,
        attempt.status == Attempt.Status.PENDING_GRADING,
    )


def _plugin(question: Mapping[str, Any]) -> QuestionTypePlugin:
    return cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )


def needs_grading(question: Mapping[str, Any], answer: JSON | None) -> bool:
    return _plugin(question).needs_grading(question["definition"], answer)


def file_fields(question: Mapping[str, Any]) -> Sequence[str]:
    return _plugin(question).file_fields(question["definition"])


def _asset(question: Mapping[str, Any], answer: JSON) -> str | None:
    for field in file_fields(question):
        value = answer.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _row(
    question: Mapping[str, Any], answer: JSON, breakdown: ScoreBreakdown, profile: str
) -> _AnswerRow | None:
    """A person's part needs the answer, so it is kept whatever the profile says."""
    graded = needs_grading(question, answer)
    if not graded and (
        not data_policy.keeps_all_answers(profile) or question_rules.is_blank(answer)
    ):
        return None
    manual_max = breakdown.max_points - breakdown.earned_points if graded else Decimal(0)
    return _AnswerRow(
        question["id"], answer, breakdown.earned_points, manual_max, _asset(question, answer)
    )


def _score(
    attempt: Attempt, answers: Mapping[str, JSON], lenient: bool = False
) -> tuple[AttemptResult, list[_AnswerRow]]:
    """Outside the transaction, so a slow plugin does not hold the write lock."""
    earned = Decimal(0)
    correct = 0
    rows: list[_AnswerRow] = []
    profile = data_policy.profile_of_attempt(attempt)
    stateless = data_policy.is_stateless(profile)
    for question in questions_of(attempt):
        answer = answers.get(question["id"])
        if answer is None:
            continue
        try:
            breakdown = evaluate(question, answer)
        except AttemptError as error:
            if lenient and error.code == "invalid_answer":
                continue
            raise
        earned += breakdown.earned_points
        correct += breakdown.correct_count or 0
        row = None if stateless else _row(question, answer, breakdown, profile)
        if row is not None:
            rows.append(row)
    pending = any(row.manual_max > 0 for row in rows)
    return AttemptResult(earned, Decimal(attempt.revision.max_score), correct, pending), rows


def evaluate(question: Mapping[str, Any], answer: JSON) -> ScoreBreakdown:
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        strategy = cast(
            ScoringStrategyPlugin,
            registry.get("scoring_strategy", question["scoring"], include_disabled=True),
        )
    except registry.UnknownPort as exc:
        raise AttemptError("revision_unavailable") from exc
    try:
        plugin.validate_submission(question["definition"], answer)
    except ValueError as exc:
        raise AttemptError("invalid_answer") from exc
    grade = plugin.grade(question["definition"], answer)
    return strategy.evaluate(grade, question["settings"])


def _check_not_played(attempt: Attempt) -> None:
    """Under "forbid" a participant keeps one finished attempt, even when two tabs got this far."""
    if attempt.participant_id is None:
        return
    if participants.rules_of(attempt.run).get(REPEAT_ATTEMPTS) != "forbid":
        return
    others = Attempt.objects.filter(
        participant_id=attempt.participant_id, status__in=Attempt.FINISHED
    )
    if others.exclude(pk=attempt.pk).exists():
        raise AttemptError("already_played")


def _is_submission_key_conflict(exc: IntegrityError) -> bool:
    """SQLite words it "UNIQUE constraint failed: attempt.submission_key"."""
    meta = Attempt._meta
    named = f"{meta.db_table}.{meta.get_field('submission_key').column}"
    _, _, columns = str(exc).partition("UNIQUE constraint failed:")
    return named in (column.strip() for column in columns.split(","))


def _store(
    attempt: Attempt,
    result: AttemptResult,
    rows: Sequence[_AnswerRow],
    key: str,
    now: datetime,
    identity: participants.Identity | None = None,
    automatic: bool = False,
) -> bool:
    """False when a concurrent request stored its result first."""
    profile = data_policy.profile_of_attempt(attempt)
    if data_policy.is_stateless(profile):
        return _store_stateless(attempt, result)
    keep_duration = data_policy.keeps_duration(profile)
    try:
        with transaction.atomic():
            _check_not_played(attempt)
            changed = Attempt.objects.filter(
                pk=attempt.pk, status=Attempt.Status.IN_PROGRESS
            ).update(
                status=(
                    Attempt.Status.PENDING_GRADING if result.pending else Attempt.Status.SUBMITTED
                ),
                submitted_at=now,
                score=result.earned_points,
                auto_score=result.earned_points,
                max_score=result.max_points,
                correct_count=result.correct_count,
                duration_ms=int((now - attempt.started_at).total_seconds() * 1000)
                if keep_duration
                else None,
                submission_key=key,
            )
            if changed:
                if identity is not None and attempt.participant is not None:
                    participants.claim_name(attempt.participant, identity, automatic=automatic)
                AttemptAnswer.objects.bulk_create(
                    AttemptAnswer(
                        attempt_id=attempt.pk,
                        question_id=row.question_id,
                        answer_json=row.answer,
                        auto_points=row.auto_points,
                        manual_max=row.manual_max,
                        asset_id=row.asset_id,
                    )
                    for row in rows
                )
                if attempt.participant_id is not None:
                    from app.domain import rewards  # rewards reads this module back

                    rewards.refresh(cast(Participant, attempt.participant))
                events.emit(
                    "attempt.submitted",
                    {
                        "attempt_id": str(attempt.id),
                        "run_id": str(attempt.run_id),
                        "score": str(result.earned_points),
                        "max_score": str(result.max_points),
                    },
                )
    except IntegrityError as exc:
        if not _is_submission_key_conflict(exc):
            raise  # e.g. from the rewards: its cause must not pose as a used key
        raise AttemptError("submission_key_used") from exc
    return bool(changed)


def _store_stateless(attempt: Attempt, result: AttemptResult) -> bool:
    """Nothing stays but a count. Only the request that finds the attempt in progress counts."""
    with transaction.atomic():  # IMMEDIATE: of two racing submissions one finds it taken
        claimed = Attempt.objects.filter(pk=attempt.pk, status=Attempt.Status.IN_PROGRESS).update(
            status=Attempt.Status.SUBMITTED
        )
        if not claimed:
            return False
        chain = [attempt.pk]
        while previous := list(
            Attempt.objects.filter(replaced_by_id=chain[0]).values_list("pk", flat=True)
        ):
            chain = [*previous, *chain]
        for attempt_id in chain:  # oldest first: a replaced attempt protects its successor
            Attempt.objects.filter(pk=attempt_id).delete()
        if attempt.run.kind != QuizRun.Kind.TEST:  # test data stay apart from the public count
            QuizRun.objects.filter(pk=attempt.run_id).update(
                stateless_submitted=F("stateless_submitted") + 1
            )
        events.emit(
            "attempt.submitted",
            {
                "run_id": str(attempt.run_id),
                "score": str(result.earned_points),
                "max_score": str(result.max_points),
            },
        )
    return True
