"""Starting and submitting attempts. The server alone decides score and times (ADR-0009)."""

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone

from app.contracts import JSON, QuestionTypePlugin, ScoreBreakdown, ScoringStrategyPlugin
from app.domain import tokens
from app.domain.models import Attempt, QuizRevision, QuizRun
from app.kernel import events, registry

# Until C1 brings deadlines and attempt limits.
ATTEMPT_LIFETIME = timedelta(hours=24)


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

    @property
    def percentage(self) -> Fraction:
        """Exact, for any comparison. Round only for display (FR-25)."""
        if not self.max_points:
            return Fraction(0)
        return Fraction(self.earned_points) / Fraction(self.max_points) * 100

    @property
    def percentage_display(self) -> float:
        return round(float(self.percentage), 2)


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


def manifest_hash(snapshot: JSON) -> str:
    """Identifies what the participant was given: the questions and their order."""
    ids = ",".join(question["id"] for question in snapshot["questions"])
    return hashlib.sha256(ids.encode()).hexdigest()


def start(run: QuizRun) -> StartedAttempt:
    if run.status != QuizRun.Status.OPEN:
        raise AttemptError("run_closed")
    revision = run.current_revision
    attempt = Attempt.objects.create(run=run, revision=revision)
    token = tokens.issue(
        tokens.AttemptClaims(
            run_id=run.id,
            revision_id=revision.id,
            attempt_id=attempt.id,
            started_at=attempt.started_at,
            expires_at=attempt.started_at + ATTEMPT_LIFETIME,
            manifest_hash=manifest_hash(revision.snapshot_json),
        )
    )
    return StartedAttempt(attempt, token, secrets.token_urlsafe(16))


def submit(
    attempt_id: UUID, token: str, answers: Mapping[str, JSON], submission_key: str
) -> AttemptResult:
    claims = _verify(token, attempt_id)
    attempt = _load(attempt_id)
    if (
        attempt.run_id != claims.run_id
        or attempt.revision_id != claims.revision_id
        or manifest_hash(attempt.revision.snapshot_json) != claims.manifest_hash
    ):
        raise AttemptError("invalid_token")
    if attempt.status == Attempt.Status.SUBMITTED:
        return _stored_result(attempt, submission_key)
    now = timezone.now()
    if _whole_second(now) > _whole_second(claims.expires_at):
        raise AttemptError("attempt_expired")
    if attempt.run.status != QuizRun.Status.OPEN:
        raise AttemptError("run_closed")
    result = _score(attempt.revision, answers)
    stored = with_retry(lambda: _store(attempt, result, submission_key, now))
    return result if stored else _stored_result(_load(attempt_id), submission_key)


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
        return Attempt.objects.select_related("run", "revision").get(pk=attempt_id)
    except Attempt.DoesNotExist as exc:
        raise AttemptError("not_found") from exc


def _whole_second(moment: datetime) -> datetime:
    return moment.replace(microsecond=0)


def _stored_result(attempt: Attempt, submission_key: str) -> AttemptResult:
    if attempt.submission_key != submission_key:
        raise AttemptError("already_submitted")
    return AttemptResult(
        Decimal(attempt.score or 0), Decimal(attempt.max_score or 0), attempt.correct_count
    )


def _score(revision: QuizRevision, answers: Mapping[str, JSON]) -> AttemptResult:
    """Outside the transaction, so a slow plugin does not hold the write lock."""
    earned = Decimal(0)
    correct = 0
    for question in revision.snapshot_json["questions"]:
        answer = answers.get(question["id"])
        if answer is None:
            continue
        breakdown = _evaluate(question, answer)
        earned += Decimal(str(breakdown.earned_points))
        correct += breakdown.correct_count or 0
    return AttemptResult(earned, Decimal(revision.max_score), correct)


def _evaluate(question: Mapping[str, Any], answer: JSON) -> ScoreBreakdown:
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
    return strategy.evaluate(question["definition"], answer, question["settings"])


def _store(attempt: Attempt, result: AttemptResult, key: str, now: datetime) -> bool:
    """False when a concurrent request stored its result first."""
    try:
        with transaction.atomic():
            changed = Attempt.objects.filter(
                pk=attempt.pk, status=Attempt.Status.IN_PROGRESS
            ).update(
                status=Attempt.Status.SUBMITTED,
                submitted_at=now,
                score=result.earned_points,
                max_score=result.max_points,
                correct_count=result.correct_count,
                duration_ms=int((now - attempt.started_at).total_seconds() * 1000),
                submission_key=key,
            )
            if changed:
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
