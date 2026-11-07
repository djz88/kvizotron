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
from django.utils import timezone

from app.contracts import (
    JSON,
    PHOTO_PUBLIC,
    QuestionTypePlugin,
    ScoreBreakdown,
    ScoringStrategyPlugin,
)
from app.domain import questions as question_rules
from app.domain import selection, settings, tokens
from app.domain.models import Attempt, AttemptAnswer, QuizRevision, QuizRun, RunRevision
from app.kernel import events, registry

# Until C1 brings deadlines and attempt limits.
ATTEMPT_LIFETIME = timedelta(hours=24)
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
    return attempt.settings_json or DEFAULT_FLOW


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


def start(run: QuizRun) -> StartedAttempt:
    _check_test_link(run, timezone.now())
    if run.status != QuizRun.Status.OPEN:
        raise AttemptError("run_closed")
    revision = run.current_revision
    _require_modules(revision)
    flow = settings.flow(run.quiz)
    attempt = Attempt(
        run=run,
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
            "store_answers": settings.resolve(settings.STORE_ANSWERS, run.quiz),
        },
    )
    attempt.settings_json["told_public"] = _told_public(attempt)
    attempt.save()
    token = _issue(attempt, attempt.started_at + ATTEMPT_LIFETIME)
    return StartedAttempt(attempt, token, secrets.token_urlsafe(16))


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
    attempt_id: UUID, token: str, answers: Mapping[str, JSON], submission_key: str
) -> AttemptResult:
    claims = _verify(token, attempt_id)
    attempt = _load(attempt_id)
    _check_claims(attempt, claims)
    if attempt.status != Attempt.Status.IN_PROGRESS:
        return _stored_result(attempt, submission_key)
    now = timezone.now()
    _check_still_valid(attempt, claims, now)
    result, rows = _score(attempt, answers)
    stored = with_retry(lambda: _store(attempt, result, rows, submission_key, now))
    return result if stored else _stored_result(_load(attempt_id), submission_key)


def verify_open(attempt_id: UUID, token: str) -> None:
    """What a submission will need, for what must happen before it, such as storing a photo."""
    claims = _verify(token, attempt_id)
    attempt = _load(attempt_id)
    _check_claims(attempt, claims)
    _check_still_valid(attempt, claims, timezone.now())


def check(attempt_id: UUID, token: str, question_id: str) -> tuple[Mapping[str, Any], str]:
    """The question and level to show, when this attempt may see a solution now (ADR-0035).

    Stores nothing. The final submission is still what counts.
    """
    claims = _verify(token, attempt_id)
    attempt = _load(attempt_id)
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
        attempt = _load(attempt_id)
        _check_claims(attempt, claims)
        current = attempt
        while current.replaced_by_id is not None:
            current = _load(current.replaced_by_id)
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
    flow = flow_of(attempt)
    replacement = Attempt.objects.create(
        run=run,
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


def _check_still_valid(attempt: Attempt, claims: tokens.AttemptClaims, now: datetime) -> None:
    _check_test_link(attempt.run, now)
    if _whole_second(now) > _whole_second(claims.expires_at):
        raise AttemptError("attempt_expired")
    if attempt.run.status != QuizRun.Status.OPEN:
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


def _whole_second(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def _stored_result(attempt: Attempt, submission_key: str) -> AttemptResult:
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
    question: Mapping[str, Any], answer: JSON, breakdown: ScoreBreakdown, store: str
) -> _AnswerRow | None:
    """A person's part needs the answer, so it is kept whatever `store_answers` says."""
    graded = needs_grading(question, answer)
    if not graded and (store != settings.StoreAnswers.ALL or question_rules.is_blank(answer)):
        return None
    manual_max = breakdown.max_points - breakdown.earned_points if graded else Decimal(0)
    return _AnswerRow(
        question["id"], answer, breakdown.earned_points, manual_max, _asset(question, answer)
    )


def _score(attempt: Attempt, answers: Mapping[str, JSON]) -> tuple[AttemptResult, list[_AnswerRow]]:
    """Outside the transaction, so a slow plugin does not hold the write lock."""
    earned = Decimal(0)
    correct = 0
    rows: list[_AnswerRow] = []
    store = (attempt.settings_json or {}).get("store_answers", settings.StoreAnswers.IMAGES)
    for question in questions_of(attempt):
        answer = answers.get(question["id"])
        if answer is None:
            continue
        breakdown = evaluate(question, answer)
        earned += breakdown.earned_points
        correct += breakdown.correct_count or 0
        row = _row(question, answer, breakdown, store)
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


def _store(
    attempt: Attempt, result: AttemptResult, rows: Sequence[_AnswerRow], key: str, now: datetime
) -> bool:
    """False when a concurrent request stored its result first."""
    try:
        with transaction.atomic():
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
                duration_ms=int((now - attempt.started_at).total_seconds() * 1000),
                submission_key=key,
            )
            if changed:
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
        raise AttemptError("submission_key_used") from exc
    return bool(changed)
