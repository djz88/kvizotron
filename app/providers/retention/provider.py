"""The trail of deletions behind `RetentionProvider`, table `retention_job` (D3)."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from django.db.models import QuerySet
from django.utils import timezone

from app.contracts import RetentionRecord

from .models import RetentionJob


def _view(row: RetentionJob) -> RetentionRecord:
    return RetentionRecord(
        id=str(row.pk),
        run_id=row.run_id,
        trigger=row.trigger,
        admin_id=row.admin_id,
        policy=row.policy,
        cutoff_at=row.cutoff_at,
        executed_at=row.executed_at,
        counts=dict(row.counts_json),
        has_fingerprint=row.fingerprint is not None,
    )


def _newest_first(rows: QuerySet[RetentionJob]) -> QuerySet[RetentionJob]:
    return rows.order_by("-executed_at", "-pk")


class LocalRetention:
    id = "local"

    def record(
        self,
        run_id: str,
        *,
        trigger: str,
        admin_id: str | None,
        policy: str,
        cutoff_at: datetime | None,
        counts: Mapping[str, int],
        fingerprint: str | None = None,
    ) -> str:
        if trigger not in RetentionJob.Trigger.values:
            raise ValueError("unknown retention trigger")  # no value: it is not for a log
        row = RetentionJob.objects.create(
            run_id=str(run_id),
            trigger=trigger,
            admin_id=admin_id,
            policy=policy,
            cutoff_at=cutoff_at,
            executed_at=timezone.now(),
            counts_json=dict(counts),
            fingerprint=fingerprint,
        )
        return str(row.pk)

    def history(self, limit: int = 200, offset: int = 0) -> Sequence[RetentionRecord]:
        rows = _newest_first(RetentionJob.objects.all())[offset : offset + limit]
        return [_view(row) for row in rows]

    def for_run(self, run_id: str) -> Sequence[RetentionRecord]:
        rows = RetentionJob.objects.filter(run_id=str(run_id))
        return [_view(row) for row in _newest_first(rows)]

    def erased(self, fingerprint: str) -> Sequence[RetentionRecord]:
        rows = RetentionJob.objects.filter(fingerprint=fingerprint)
        return [_view(row) for row in _newest_first(rows)]
