"""Test links: a hidden run fixed to one version, played without an account (ADR-0044)."""

import secrets
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from app.domain import authoring
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Quiz,
    QuizRevision,
    QuizRun,
    RunRevision,
    RunTestLink,
)
from app.kernel import audit


def _audit(action: str, link: RunTestLink, admin_id: str, details: dict[str, Any] | None = None):
    """Never the token: it is a working address."""
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=f"test_link.{action}",
        entity_type="test_link",
        entity_id=str(link.id),
        details=details,
    )


def create(
    quiz: Quiz, revision: QuizRevision | None, *, expires_at: datetime | None, admin_id: str
) -> RunTestLink:
    """`revision=None` freezes a copy of the draft, which must pass the publication check."""
    authoring.ensure_editable(quiz)
    with transaction.atomic():
        chosen = revision if revision is not None else authoring.freeze_copy(quiz)
        run = QuizRun.all_kinds.create(
            quiz=quiz, kind=QuizRun.Kind.TEST, run_no=None, current_revision=chosen
        )
        RunRevision.objects.create(
            run=run, revision=chosen, active_from=run.opened_at, max_score=chosen.max_score
        )
        link = RunTestLink.objects.create(
            run=run, token=secrets.token_urlsafe(32), expires_at=expires_at, created_by=admin_id
        )
        _audit("created", link, admin_id, {"revision_no": chosen.revision_no})
    return link


def is_playable(link: RunTestLink, now: datetime) -> bool:
    return link.is_playable(now)


def find_playable(token: str) -> RunTestLink | None:
    link = RunTestLink.objects.filter(token=token).select_related("run", "run__quiz").first()
    return link if link is not None and link.is_playable(timezone.now()) else None


def cancel(link: RunTestLink, *, admin_id: str) -> None:
    """Attempts stay, and the admin can still read them."""
    with transaction.atomic():
        QuizRun.all_kinds.filter(pk=link.run_id, status=QuizRun.Status.OPEN).update(
            status=QuizRun.Status.CLOSED, closed_at=timezone.now()
        )
        _audit("cancelled", link, admin_id)
    link.run.refresh_from_db()


def _assets_of(link: RunTestLink) -> list[str]:
    rows = AttemptAnswer.objects.filter(attempt__run=link.run_id, asset_id__isnull=False)
    return list(rows.values_list("asset_id", flat=True))


def delete_attempts(link: RunTestLink, *, admin_id: str) -> list[str]:
    """Returns the photos' asset ids, for the caller to remove once this has been committed."""
    with transaction.atomic():
        assets = _assets_of(link)
        Attempt.objects.filter(run=link.run_id).delete()
        _audit("attempts_deleted", link, admin_id)
    return assets


def delete(link: RunTestLink, *, admin_id: str) -> list[str]:
    """Dependent rows first, as everything here is protected. A published revision stays.

    Returns the photos' asset ids, for the caller to remove once this has been committed.
    """
    with transaction.atomic():
        assets = _assets_of(link)
        run = link.run
        revision_id = run.current_revision_id
        _audit("deleted", link, admin_id)
        Attempt.objects.filter(run=run).delete()
        RunRevision.objects.filter(run=run).delete()
        link.delete()
        run.delete()
        QuizRevision.all_kinds.filter(pk=revision_id, status=QuizRevision.Status.TEST_COPY).delete()
    return assets
