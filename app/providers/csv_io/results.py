"""Results export jobs behind `ResultsExporterProvider` (D2).

Jobs wait in `export_job` until the worker claims them. The files lie under
`<KVZ_MEDIA_PATH>/exports/<job id>/`; the media view never serves them, only a route that
checks the admin through `path()`.
"""

import io
import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from app.contracts import ExportJobGone, ExportJobView, ExportTable
from app.providers.csv_io import limits, writer
from app.providers.csv_io.models import ExportJobRecord

# Identifies this process. A queued or running job of another boot will never finish.
BOOT = uuid.uuid4().hex

Status = ExportJobRecord.Status
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
DIRECTORY_MODE = 0o750
FILE_MODE = 0o640  # never world-readable, not even while being written
RUN_DATA_DELETED = "run_data_deleted"


def _private(path: str, flags: int) -> int:
    """`open()` opener: a new file gets FILE_MODE from the start, whatever the umask."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    os.fchmod(descriptor, FILE_MODE)
    return descriptor


def _directory(job_id: Any) -> Path:
    return Path(settings.KVZ_MEDIA_PATH) / "exports" / str(job_id)


def _remove(job_id: Any) -> None:
    shutil.rmtree(_directory(job_id), ignore_errors=True)


def _remove_or_raise(job_id: Any) -> None:
    """For a deletion that must not count as done while the files are still there."""
    try:
        shutil.rmtree(_directory(job_id))
    except FileNotFoundError:
        pass  # `exists()` would also answer False for a directory it may not look into


def _view(record: ExportJobRecord) -> ExportJobView:
    report = record.report_json or {}
    return ExportJobView(
        id=str(record.pk),
        status=record.status,
        choices=record.choices_json,
        files=list(report.get("files", [])),
        error=report.get("error"),
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


def _prefix(choices: Mapping[str, Any]) -> str:
    """The domain builds the name; a name that could leave the directory is a bug there."""
    name = str(choices.get("name") or "")
    if name and not SAFE_NAME.fullmatch(name):
        raise ValueError(f"unsafe export name: {name!r}")
    return name


def _csv_name(prefix: str, table: ExportTable) -> str:
    return f"{prefix}-{table.name}.csv" if prefix else f"{table.name}.csv"


class CsvResultsExporter:
    id = "csv"

    def _tidy(self) -> None:
        """No scheduler exists: expired jobs go, and jobs of a previous boot stop waiting."""
        expired = ExportJobRecord.objects.filter(expires_at__lte=timezone.now())
        for job_id in list(expired.values_list("pk", flat=True)):
            _remove(job_id)
        expired.delete()
        ExportJobRecord.objects.filter(status__in=[Status.QUEUED, Status.RUNNING]).exclude(
            boot=BOOT
        ).update(status=Status.INTERRUPTED)

    def _record(self, job_id: str, admin_id: str) -> ExportJobRecord:
        try:
            pk = UUID(str(job_id))
        except ValueError as exc:
            raise ExportJobGone(str(job_id)) from exc
        record = ExportJobRecord.objects.filter(
            pk=pk, admin_id=admin_id, expires_at__gt=timezone.now()
        ).first()
        if record is None:
            raise ExportJobGone(str(job_id))
        return record

    def create(self, admin_id: str, choices: Mapping[str, Any]) -> str:
        self._tidy()
        now = timezone.now()
        record = ExportJobRecord.objects.create(
            admin_id=admin_id,
            kind="results",
            status=Status.QUEUED,
            choices_json=dict(choices),
            report_json={"files": [], "error": None},
            boot=BOOT,
            created_at=now,
            expires_at=now + limits.EXPORT_LIFETIME,
        )
        return str(record.pk)

    def job(self, job_id: str, admin_id: str) -> ExportJobView:
        return _view(self._record(job_id, admin_id))

    def jobs(self, admin_id: str) -> Sequence[ExportJobView]:
        self._tidy()
        records = ExportJobRecord.objects.filter(
            admin_id=admin_id, expires_at__gt=timezone.now()
        ).order_by("-created_at", "-pk")
        return [_view(record) for record in records]

    def claim_next(self) -> ExportJobView | None:
        """The oldest queued job whose admin has a free slot, while the app has one."""
        with transaction.atomic():  # IMMEDIATE: no other worker reads between check and write
            self._tidy()
            running = ExportJobRecord.objects.filter(status=Status.RUNNING)
            if running.count() >= limits.EXPORT_SLOTS_TOTAL:
                return None
            busy = [
                row["admin_id"]
                for row in running.values("admin_id")
                .annotate(n=Count("pk"))
                .filter(n__gte=limits.EXPORT_SLOTS_PER_ADMIN)
            ]
            record = (
                ExportJobRecord.objects.filter(status=Status.QUEUED, boot=BOOT)
                .exclude(admin_id__in=busy)
                .order_by("created_at", "pk")
                .first()
            )
            if record is None:
                return None
            ExportJobRecord.objects.filter(pk=record.pk).update(status=Status.RUNNING)
            record.status = Status.RUNNING
            return _view(record)

    def write(
        self,
        job_id: str,
        tables: Sequence[ExportTable],
        photos: Mapping[str, str],
        bundle: bool,
    ) -> None:
        record = ExportJobRecord.objects.filter(pk=job_id).first()
        if record is None or record.status != Status.RUNNING:
            _remove(job_id)  # restarted, expired or failed meanwhile: no orphan files
            return
        prefix = _prefix(record.choices_json)
        directory = _directory(job_id)
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(mode=DIRECTORY_MODE, exist_ok=True)
        os.chmod(directory, DIRECTORY_MODE)  # mkdir's mode is reduced by the umask
        if bundle:
            name = f"{prefix}.zip" if prefix else "results.zip"
            with (
                open(directory / name, "wb", opener=_private) as handle,
                zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive,
            ):
                for table in tables:
                    with (
                        archive.open(_csv_name(prefix, table), "w") as entry,
                        io.TextIOWrapper(entry, encoding="utf-8", newline="") as out,
                    ):
                        writer.write_table(table, out)
                for photo_name, photo_path in photos.items():
                    if os.path.isfile(photo_path):  # deleted since the query: leave it out
                        archive.write(photo_path, photo_name)
            files = [name]
        else:
            files = []
            for table in tables:
                name = _csv_name(prefix, table)
                with open(
                    directory / name, "w", encoding="utf-8", newline="", opener=_private
                ) as out:
                    writer.write_table(table, out)
                files.append(name)
        updated = ExportJobRecord.objects.filter(pk=job_id, status=Status.RUNNING).update(
            status=Status.DONE, report_json={"files": files, "error": None}
        )
        if not updated:  # the job stopped running while its files were written
            _remove(job_id)

    def fail(self, job_id: str, code: str) -> None:
        """Only a running job fails; a done one keeps its files, anything else keeps none."""
        updated = ExportJobRecord.objects.filter(pk=job_id, status=Status.RUNNING).update(
            status=Status.FAILED, report_json={"files": [], "error": code}
        )
        if updated or not ExportJobRecord.objects.filter(pk=job_id, status=Status.DONE).exists():
            _remove(job_id)

    def restart(self, job_id: str, admin_id: str) -> str:
        """A new job with the same choices in place of an interrupted or failed one."""
        self._tidy()  # a job of a previous boot turns interrupted first
        record = self._record(job_id, admin_id)
        if record.status not in (Status.INTERRUPTED, Status.FAILED):
            raise ExportJobGone(str(job_id))
        new_id = self.create(admin_id, record.choices_json)
        _remove(record.pk)
        ExportJobRecord.objects.filter(pk=record.pk).delete()
        return new_id

    def path(self, job_id: str, admin_id: str, name: str) -> str:
        record = self._record(job_id, admin_id)
        if record.status != Status.DONE or name not in (record.report_json or {}).get("files", []):
            raise ExportJobGone(str(job_id))
        return str(_directory(record.pk) / name)

    def delete_for_runs(self, quiz_id: str, run_ids: Sequence[str]) -> None:
        deleted = {str(run_id) for run_id in run_ids}
        if not deleted:
            return
        for record in ExportJobRecord.objects.all():
            choices = record.choices_json or {}
            whole_quiz = choices.get("all_runs") and choices.get("quiz") == str(quiz_id)
            if not whole_quiz and deleted.isdisjoint(choices.get("runs") or []):
                continue
            # A job that finished meanwhile matches no row here and is deleted like any other;
            # one still writing finds itself no longer running and removes its own files.
            stopped = ExportJobRecord.objects.filter(
                pk=record.pk, status__in=[Status.QUEUED, Status.RUNNING]
            ).update(status=Status.FAILED, report_json={"files": [], "error": RUN_DATA_DELETED})
            _remove_or_raise(record.pk)  # before the row, so a failure can be retried
            already_stopped = (
                record.status == Status.FAILED
                and (record.report_json or {}).get("error") == RUN_DATA_DELETED
            )
            if not stopped and not already_stopped:  # one stopped stays, for its admin to restart
                ExportJobRecord.objects.filter(pk=record.pk).delete()
