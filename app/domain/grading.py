"""What a person decides about a stored answer. The score follows (ADR-0047, AC-56)."""

from decimal import Decimal
from typing import Any, cast

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from app.domain import authoring, rewards
from app.domain.models import Attempt, AttemptAnswer, Participant, Quiz, QuizRun
from app.kernel import audit

PLACES = 4


class InvalidPoints(Exception):
    """Outside zero to the manual maximum, too exact to store, or nothing left to grade."""


def waiting_rows(run: QuizRun) -> QuerySet[AttemptAnswer]:
    return AttemptAnswer.objects.filter(
        attempt__run=run,
        attempt__status__in=Attempt.FINISHED,
        manual_max__gt=0,
        manual_points__isnull=True,
        removed=False,
    )


def waiting_in_quiz(quiz: Quiz) -> int:
    """Test runs are looked after from their own link."""
    return AttemptAnswer.objects.filter(
        attempt__run__quiz=quiz,
        attempt__run__kind=QuizRun.Kind.NORMAL,
        attempt__status__in=Attempt.FINISHED,
        manual_max__gt=0,
        manual_points__isnull=True,
        removed=False,
    ).count()


def waiting(run: QuizRun) -> int:
    return waiting_rows(run).count()


def run_assets(run: QuizRun) -> list[str]:
    rows = AttemptAnswer.objects.filter(attempt__run=run, asset_id__isnull=False)
    return [str(asset) for asset in rows.values_list("asset_id", flat=True)]


def recalculated(attempt: Attempt) -> None:
    """Call within a transaction. An attempt from before stored points keeps its score as base."""
    rows = AttemptAnswer.objects.filter(attempt=attempt)
    manual = rows.aggregate(total=Sum("manual_points"))["total"] or Decimal(0)
    base = attempt.auto_score if attempt.auto_score is not None else Decimal(0)
    fields: dict[str, Any] = {"score": base + manual}
    still_waits = rows.filter(manual_max__gt=0, manual_points__isnull=True, removed=False).exists()
    if attempt.status == Attempt.Status.PENDING_GRADING and not still_waits:
        fields["status"] = Attempt.Status.SUBMITTED
    Attempt.objects.filter(pk=attempt.pk).update(**fields)
    attempt.refresh_from_db()
    if attempt.participant_id is not None:  # the official attempt may have changed with it
        rewards.refresh(cast(Participant, attempt.participant))


def _audit(action: str, answer: AttemptAnswer, admin_id: str, **details: Any) -> None:
    """Never what was answered, and never the address of a photo."""
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="attempt_answer",
        entity_id=str(answer.id),
        details={"question_id": answer.question_id, **details},
    )


def _too_exact(points: Decimal) -> bool:
    return points != round(points, PLACES)


def save_manual(answer: AttemptAnswer, points: Decimal, *, admin_id: str) -> None:
    authoring.ensure_editable(answer.attempt.run.quiz)
    with transaction.atomic():
        current = AttemptAnswer.objects.select_related("attempt").get(pk=answer.pk)
        if (
            not points.is_finite()
            or current.removed
            or current.manual_max <= 0
            or not 0 <= points <= current.manual_max
            or _too_exact(points)
        ):
            raise InvalidPoints
        now = timezone.now()
        AttemptAnswer.objects.filter(pk=current.pk).update(
            manual_points=points, graded_by=admin_id, graded_at=now
        )
        recalculated(current.attempt)
        _audit("answer.graded", current, admin_id, points=str(points))
    answer.refresh_from_db()


def remove_photo(answer: AttemptAnswer, *, admin_id: str) -> str | None:
    """Returns the asset to delete once this has been committed. Automatic points stay."""
    authoring.ensure_editable(answer.attempt.run.quiz)
    with transaction.atomic():
        current = AttemptAnswer.objects.select_related("attempt").get(pk=answer.pk)
        if current.removed:
            return None
        asset = current.asset_id
        AttemptAnswer.objects.filter(pk=current.pk).update(
            removed=True,
            asset_id=None,
            approved=False,
            answer_json={},
            manual_points=0,
            graded_by=admin_id,
            graded_at=timezone.now(),
        )
        recalculated(current.attempt)
        _audit("answer.photo_removed", current, admin_id)
    answer.refresh_from_db()
    return asset


def set_approved(answer: AttemptAnswer, approved: bool, *, admin_id: str) -> None:
    """Whether this photo may appear in a public walkthrough, when its level allows that."""
    authoring.ensure_editable(answer.attempt.run.quiz)
    with transaction.atomic():
        current = AttemptAnswer.objects.get(pk=answer.pk)
        if current.removed:
            return
        AttemptAnswer.objects.filter(pk=current.pk).update(approved=approved)
        _audit("answer.approved", current, admin_id, approved=approved)
    answer.refresh_from_db()
