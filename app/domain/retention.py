"""Deleting the data a run collected, and keeping an anonymous summary of it (FR-34, D3).

One path for the expiry of the period and for an admin's "delete now". It works in short
transactions, so a live quiz is not starved of the single SQLite writer. The summary is stored
first and holds what was counted, so a purge that stopped halfway resumes with the same record.
"""

import logging
from collections.abc import Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.crypto import salted_hmac

from app.contracts import (
    ParticipantPolicyPlugin,
    ResultsExporterProvider,
    RetentionProvider,
    RetentionRecord,
)
from app.domain import branding, data_policy, results, run_schedule, run_stats, settings
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    HiddenAnswerValue,
    Participant,
    QuizRun,
    RewardEntitlement,
)
from app.domain.participants import email_key_of
from app.kernel import audit, events, registry

__all__ = [
    "AUTOMATIC",
    "BATCH",
    "ERASURE",
    "Found",
    "MANUAL",
    "Refused",
    "SWEEP_AGE",
    "deletable",
    "delete_now",
    "erase",
    "erased_records",
    "fingerprint",
    "held_runs",
    "purge_run",
    "release_held",
    "run_pass",
    "search_email",
    "search_name",
    "sweep",
]

logger = logging.getLogger(__name__)

# None outside a pass. Inside one: whether the missing exporter was already reported.
_exporter_reported: ContextVar[bool | None] = ContextVar("exporter_reported", default=None)

BATCH = 200  # attempts in one transaction
AUTOMATIC = "automatic"
MANUAL = "manual"
ERASURE = "erasure"
LATE_EXPORTS_RETRY = timedelta(hours=24)  # how long after a purge a pass looks for its exports
PENDING = "late_exports_pending"  # in the summary from the final commit until the removal worked
SWEEP_AGE = timedelta(hours=1)  # a younger photo may belong to a submission in progress
_ENDED = (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED)


class Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _tally(
    attempts: QuerySet[Attempt], people: QuerySet[Participant], hidden_values: int
) -> dict[str, int]:
    answers = AttemptAnswer.objects.filter(attempt__in=attempts)
    photos = answers.filter(asset_id__isnull=False).values("asset_id").distinct()
    return {
        "attempts": attempts.count(),
        "answers": answers.count(),
        "participants": people.count(),
        "entitlements": RewardEntitlement.objects.filter(participant__in=people).count(),
        "hidden_values": hidden_values,
        "photos": photos.count(),
    }


def _counts(run: QuizRun) -> dict[str, int]:
    return _tally(
        Attempt.objects.filter(run=run),
        Participant.objects.filter(run=run),
        HiddenAnswerValue.objects.filter(run=run).count(),
    )


def _summarized(run_id: UUID, trigger: str, admin_id: str | None) -> bool:
    """False when the data are already gone. A summary already there means a purge is resuming.

    The summary keeps who asked, so whoever finishes the purge leaves the record it started.
    """
    with transaction.atomic():
        run = QuizRun.all_kinds.get(pk=run_id)
        if run.data_deleted_at is not None:
            return False
        if not run.retention_summary_json:
            summary = {
                **run_stats.freeze(run_stats.of_run(run)),
                "counts": _counts(run),
                "trigger": trigger,
                "admin_id": admin_id,
            }
            QuizRun.all_kinds.filter(pk=run_id).update(retention_summary_json=summary)
    return True


def _delete_batch(attempts: QuerySet[Attempt]) -> tuple[list[UUID], list[str]]:
    """The attempts deleted and the photos that lost them, to be deleted after this commits."""
    with transaction.atomic():
        ids = list(attempts.order_by("pk").values_list("pk", flat=True)[:BATCH])
        # A link protects its target, also from an attempt that stays or waits for a later batch.
        Attempt.objects.filter(replaced_by__in=ids).update(replaced_by=None)
        assets = AttemptAnswer.objects.filter(attempt_id__in=ids, asset_id__isnull=False)
        found = sorted({str(asset) for asset in assets.values_list("asset_id", flat=True)})
        Attempt.objects.filter(pk__in=ids).delete()
    return ids, found


def _delete_photos(run_id: UUID, assets: Sequence[str]) -> None:
    """The deletion stands, and the sweep of a later pass finds a file left behind."""
    for asset_id in assets:
        try:
            branding.media().delete_image(asset_id)
        except Exception as exc:  # the type only: a message could carry a path or a value
            logger.error("Run %s: a photo was not deleted: %s", run_id, type(exc).__name__)


def _finish(run_id: UUID, trigger: str, admin_id: str | None) -> bool:
    """Whoever changes the row here is the one purge that leaves a record."""
    with transaction.atomic():
        run = QuizRun.all_kinds.get(pk=run_id)
        if run.data_deleted_at is not None:
            return False
        HiddenAnswerValue.objects.filter(run=run).delete()
        RewardEntitlement.objects.filter(run=run).delete()
        Participant.objects.filter(run=run).delete()
        policy = data_policy.of(run)
        cutoff_at = data_policy.deletion_at(run)
        summary = run.retention_summary_json
        # A summary from before the trigger was kept has none: the one finishing it stands in.
        if "trigger" in summary:
            trigger, admin_id = summary["trigger"], summary.get("admin_id")
        changed = QuizRun.all_kinds.filter(pk=run_id, data_deleted_at__isnull=True).update(
            retention_json={**policy, data_policy.PROFILE: settings.DataProfile.NONE.value},
            retention_summary_json={**summary, PENDING: True},
            stateless_submitted=summary["submitted"],
            status=QuizRun.Status.ARCHIVED,
            retention_held_at=None,
            data_deleted_at=timezone.now(),
        )
        if not changed:
            return False
        cast(RetentionProvider, registry.get("retention", "local")).record(
            str(run_id),
            trigger=trigger,
            admin_id=admin_id,
            policy=policy[data_policy.PERIOD],
            cutoff_at=cutoff_at,
            counts=summary["counts"],
        )
        audit.record(
            actor_type="admin" if admin_id else "system",
            actor_id=admin_id,
            action="run.data_deleted",
            entity_type="run",
            entity_id=str(run_id),
            details={"counts": summary["counts"]},
        )
        events.emit("retention.executed", {"run_id": str(run_id)})
    return True


def _exporter(run: QuizRun) -> ResultsExporterProvider | None:
    """None without the module: then there are no exports, which is not a failed removal."""
    try:
        return cast(ResultsExporterProvider, registry.get("results_exporter", "csv"))
    except LookupError:
        if not _exporter_reported.get():  # a pass says it once, not for each of its runs
            logger.warning("Run %s: no results exporter, so no exports were deleted", run.pk)
            if _exporter_reported.get() is False:
                _exporter_reported.set(True)
        return None


def _delete_exports(run: QuizRun) -> None:
    """Before the run counts as deleted. A failure stops the purge, and the next one retries."""
    exporter = _exporter(run)
    if exporter is not None:
        exporter.delete_for_runs(str(run.quiz_id), [str(run.pk)])


def _delete_late_exports(run: QuizRun) -> bool:
    """After the commit, for a job created while the purge ran. The deletion stands either way."""
    try:
        _delete_exports(run)
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("Run %s: exports were not deleted: %s", run.pk, type(exc).__name__)
        return False
    return True


def _clear_pending(run_id: UUID) -> None:
    """A failed clear is only logged: the next pass removes the exports once more."""
    try:
        with transaction.atomic():
            row = QuizRun.all_kinds.filter(pk=run_id)
            summary = row.values_list("retention_summary_json", flat=True).first() or {}
            if PENDING in summary:
                row.update(
                    retention_summary_json={k: v for k, v in summary.items() if k != PENDING}
                )
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("Run %s: the pending mark was not cleared: %s", run_id, type(exc).__name__)


def _settle_late_exports(run: QuizRun) -> None:
    """Removes them and, when that worked, the mark that asks a later pass to try again."""
    if _delete_late_exports(run):
        _clear_pending(run.pk)


def purge_run(run: QuizRun, *, trigger: str, admin_id: str | None) -> bool:
    """False when the run's data were already deleted. An exception leaves it resumable."""
    if not _summarized(run.pk, trigger, admin_id):
        run.refresh_from_db()
        return False
    while True:
        ids, assets = _delete_batch(Attempt.objects.filter(run_id=run.pk))
        if not ids:
            break
        _delete_photos(run.pk, assets)
    _delete_exports(run)
    done = _finish(run.pk, trigger, admin_id)
    if done:
        _settle_late_exports(run)
    run.refresh_from_db()
    return done


def deletable(run: QuizRun) -> bool:
    """Whether "delete now" has anything to do on this run."""
    return run.status in _ENDED and run.data_deleted_at is None


def delete_now(run: QuizRun, *, admin_id: str) -> None:
    """An admin's request for what the period would do anyway. `Refused` before a run has ended."""
    status = QuizRun.all_kinds.values_list("status", flat=True).get(pk=run.pk)
    if status not in _ENDED:
        raise Refused("not_ended")
    purge_run(run, trigger=MANUAL, admin_id=admin_id)


@dataclass(frozen=True)
class Found:
    """One participant row an erasure search matched. For the logged-in administration only."""

    participant_id: str
    run_id: str
    quiz_id: str
    run_no: int | None
    display_name: str
    email: str | None


def _found(row: Participant) -> Found:
    return Found(
        participant_id=str(row.pk),
        run_id=str(row.run_id),
        quiz_id=str(row.run.quiz_id),
        run_no=row.run.run_no,
        display_name=row.display_name,
        email=row.email,
    )


def _searchable() -> QuerySet[Participant]:
    """`Participant.objects` has no filter on the kind of run, so test runs count too."""
    return Participant.objects.select_related("run").order_by("run__quiz_id", "run_id", "pk")


def search_email(raw: str) -> list[Found]:
    """By `email_key`: addresses are stored as typed, a row without a key is not found."""
    key = email_key_of(raw)
    if not key:
        return []
    return [_found(row) for row in _searchable().filter(email_key=key)]


def search_name(raw: str) -> list[Found]:
    """An empty key belongs to everyone who gave no name, so it must not match them."""
    key = cast(ParticipantPolicyPlugin, registry.get("participant_policy", "basic")).name_key(raw)
    if not key:
        return []
    return [_found(row) for row in _searchable().filter(name_key=key)]


def fingerprint(raw_email: str) -> str:
    """Confirms an address erased earlier without storing it. Depends on the server secret."""
    normalised = email_key_of(raw_email) or ""
    return salted_hmac("kvz-erasure", normalised, algorithm="sha256").hexdigest()


def _leave_summary(run_id: UUID, counts: dict[str, int]) -> None:
    """A purge begun earlier counted these rows; its record must not, the erasure's does."""
    row = QuizRun.all_kinds.filter(pk=run_id, data_deleted_at__isnull=True)
    summary = row.values_list("retention_summary_json", flat=True).first()
    if not summary:
        return
    left = {key: value - counts.get(key, 0) for key, value in summary["counts"].items()}
    if any(value < 0 for value in left.values()):  # the rows and the summary disagree
        logger.error("Run %s: the summary counts fell below zero, so they were clamped", run_id)
        left = {key: max(0, value) for key, value in left.items()}
    row.update(retention_summary_json={**summary, "counts": left})


def _erase_in_run(
    run: QuizRun, participant_ids: Sequence[str], *, admin_id: str, mark: str | None
) -> list[str]:
    """The photos to delete after the commit. All or nothing: a retry must count the same rows.

    One person has few attempts, so this stays short, and in one transaction nobody can start
    another attempt between the last batch and the deletion of the row it would need.
    """
    photos: list[str] = []
    with transaction.atomic():
        people = Participant.objects.filter(run=run, pk__in=participant_ids)
        if not people.exists():  # another request got here first, and it left the record
            return photos
        attempts = Attempt.objects.filter(participant__in=people)
        counts = _tally(attempts, people, 0)  # a hidden value belongs to no participant
        _leave_summary(run.pk, counts)
        while True:
            ids, assets = _delete_batch(attempts)
            if not ids:
                break
            photos.extend(assets)
        RewardEntitlement.objects.filter(participant__in=people).delete()
        people.delete()
        cast(RetentionProvider, registry.get("retention", "local")).record(
            str(run.pk),
            trigger=ERASURE,
            admin_id=admin_id,
            policy=data_policy.of(run)[data_policy.PERIOD],
            cutoff_at=data_policy.deletion_at(run),
            counts=counts,
            fingerprint=mark,
        )
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.participants_erased",
            entity_type="run",
            entity_id=str(run.pk),
            details={"counts": counts},
        )
        events.emit("retention.executed", {"run_id": str(run.pk)})
    return photos


def _clear_board(run_id: UUID) -> None:
    """After the commit, so no read rebuilds the board from old rows. A failure is only logged."""
    try:
        results.clear_board_cache(run_id)
    except Exception as exc:
        logger.error("Run %s: the board cache was not cleared: %s", run_id, type(exc).__name__)


def erase(participant_ids: Sequence[str], *, admin_id: str, email: str | None = None) -> None:
    """Deletes these people from any run in any state. `email` only when the search was by it.

    The rest of each run stays. An export that cannot be removed raises before that run loses
    anything, so calling this again with the same ids finishes the job.
    """
    mark = fingerprint(email) if email and email.strip() else None
    affected = Participant.objects.filter(pk__in=participant_ids).values("run_id")
    for run in QuizRun.all_kinds.filter(pk__in=affected).order_by("pk"):
        _delete_exports(run)
        photos = _erase_in_run(run, participant_ids, admin_id=admin_id, mark=mark)
        _clear_board(run.pk)
        _delete_photos(run.pk, photos)
        _delete_late_exports(run)


def erased_records(raw_email: str) -> Sequence[RetentionRecord]:
    """Newest first: whether and when this address was erased, and by whom."""
    trail = cast(RetentionProvider, registry.get("retention", "local"))
    return trail.erased(fingerprint(raw_email))


def _held() -> QuerySet[QuizRun]:
    return QuizRun.objects.filter(retention_held_at__isnull=False, data_deleted_at__isnull=True)


def held_runs() -> list[QuizRun]:
    """The runs waiting for an admin's confirmation, the longest waiting first."""
    return list(_held().select_related("quiz").order_by("closed_at", "pk"))


def release_held(run_ids: Sequence[str], *, admin_id: str) -> int:
    """Confirms these runs once, so the next pass deletes them. Says how many were still held.

    The list is what the admin saw: a run held after that stays held.
    """
    with transaction.atomic():
        ids = [
            str(pk)
            for pk in _held().filter(pk__in=run_ids).order_by("pk").values_list("pk", flat=True)
        ]
        if not ids:
            return 0
        QuizRun.objects.filter(pk__in=ids).update(retention_held_at=None)
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="retention.held_released",
            entity_type="retention",
            entity_id="held",
            details={"run_ids": ids, "count": len(ids)},
        )
    return len(ids)


def _in_pass(run: QuizRun, now: datetime) -> bool:
    """A purge already started counts too, or a permanent or held run would stay half deleted."""
    resuming = bool(run.retention_summary_json) and run.data_deleted_at is None
    return resuming or data_policy.is_due(run, now)


def _purged_in_pass(run: QuizRun, now: datetime) -> bool:
    """One run failing must not stop the others, and the next pass picks it up again."""
    try:
        run.refresh_from_db()  # an admin may have held it since the pass listed the runs
        return _in_pass(run, now) and purge_run(run, trigger=AUTOMATIC, admin_id=None)
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("Run %s: data were not deleted: %s", run.pk, type(exc).__name__)
        return False


def sweep(now: datetime) -> int:
    """Removes old participant photos no answer refers to, and says how many went."""
    try:
        storage = branding.media()
    except LookupError:
        logger.warning("No media storage, so no photos were swept")
        return 0
    # Candidates first: a reference written after them is still seen below.
    candidates = storage.private_assets_older_than(now - SWEEP_AGE)
    used = set(
        AttemptAnswer.objects.filter(asset_id__isnull=False).values_list("asset_id", flat=True)
    )
    removed = 0
    for asset_id in candidates:
        if asset_id in used:
            continue
        try:
            storage.delete_image(asset_id)
        except Exception as exc:  # the type only: a message could carry a path or a value
            logger.error("Photo %s was not deleted: %s", asset_id, type(exc).__name__)
        else:
            removed += 1
    return removed


def _retry_late_exports(now: datetime, skip: set[UUID], stop: Callable[[], bool] | None) -> None:
    """Only for a removal that did not work: `delete_for_runs` also takes every "all runs" export.

    A crash between the final commit and the removal after it leaves the mark in the summary.
    """
    recent = QuizRun.objects.filter(
        data_deleted_at__gte=now - LATE_EXPORTS_RETRY,
        **{f"retention_summary_json__{PENDING}": True},
    )
    for run in recent.order_by("pk"):
        if stop is not None and stop():
            return
        if run.pk not in skip:
            _settle_late_exports(run)


def run_pass(now: datetime | None = None, stop: Callable[[], bool] | None = None) -> int:
    """The number of runs whose data this pass deleted. A skipped or failed run is not counted.

    `stop` is read before each run. Once it says so the pass ends there, and the next pass
    continues: nothing a stopped purge did is lost, as the summary is kept.
    """
    now = now or timezone.now()
    try:
        run_schedule.settle(now)  # a run nobody visited since its deadline has no date yet
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("Deadlines were not settled: %s", type(exc).__name__)
    runs = list(QuizRun.objects.filter(data_deleted_at__isnull=True))
    purged: set[UUID] = set()
    reported = _exporter_reported.set(False)
    try:
        for run in runs:
            if stop is not None and stop():
                return len(purged)
            if _purged_in_pass(run, now):
                purged.add(run.pk)
        _retry_late_exports(now, purged, stop)
    finally:
        _exporter_reported.reset(reported)
    if stop is not None and stop():
        return len(purged)
    try:
        sweep(now)
    except Exception as exc:  # the type only: a message could carry a path or a value
        logger.error("The sweep failed: %s", type(exc).__name__)
    return len(purged)
