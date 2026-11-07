"""CSV and ZIP behind the importer and exporter contracts (ADR-0032, ADR-0045)."""

import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from app.contracts import ExportedFile, ImportJob, ImportJobGone, ImportRefused, ParsedFile
from app.providers.csv_io import limits, reader, writer
from app.providers.csv_io.models import ImportJobRecord


def _path(job_id: Any) -> Path:
    """Under the media volume, but the media view serves only registered assets."""
    return Path(settings.KVZ_MEDIA_PATH) / "imports" / str(job_id)


def _remove(job_id: Any) -> None:
    _path(job_id).unlink(missing_ok=True)


class CsvImporter:
    id = "csv"

    def guide(self, name: str) -> bytes:
        return (Path(__file__).parent / "sample" / name).read_bytes()

    def _purge(self, admin_id: str) -> None:
        """No scheduler exists, so uploads clean up after each other."""
        old = ImportJobRecord.objects.filter(expires_at__lte=timezone.now()) | (
            ImportJobRecord.objects.filter(
                admin_id=admin_id, status=ImportJobRecord.Status.UPLOADED
            )
        )
        for job_id in list(old.values_list("pk", flat=True)):
            _remove(job_id)
        old.delete()

    def _write(self, job_id: Any, chunks: Iterable[bytes]) -> None:
        path = _path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("wb") as file:
            for chunk in chunks:
                written += len(chunk)
                if written > limits.MAX_UPLOAD_BYTES:
                    break
                file.write(chunk)
        if written > limits.MAX_UPLOAD_BYTES:
            path.unlink(missing_ok=True)
            raise ImportRefused(_("The file is larger than 100 MB."))
        os.chmod(path, 0o640)

    def begin(self, admin_id: str, target: Mapping[str, str], chunks: Iterable[bytes]) -> str:
        self._purge(admin_id)
        now = timezone.now()
        record = ImportJobRecord(
            admin_id=admin_id,
            target_json=dict(target),
            created_at=now,
            expires_at=now + limits.JOB_LIFETIME,
        )
        try:
            self._write(record.pk, chunks)
            reader.parse_file(_path(record.pk))
        except Exception:  # whatever went wrong, no file may stay without its record
            _remove(record.pk)
            raise
        record.save()
        return str(record.pk)

    def job(self, job_id: str, admin_id: str) -> ImportJob:
        try:
            pk = UUID(str(job_id))
        except ValueError as exc:
            raise ImportJobGone(str(job_id)) from exc
        record = ImportJobRecord.objects.filter(
            pk=pk, admin_id=admin_id, expires_at__gt=timezone.now()
        ).first()
        if record is None:
            raise ImportJobGone(str(job_id))
        return ImportJob(
            str(record.pk), record.target_json, record.mapping_json, record.report_json
        )

    def read(self, job_id: str) -> ParsedFile:
        if not _path(job_id).is_file():
            raise ImportJobGone(job_id)
        return reader.parse_file(_path(job_id))

    def read_image(self, job_id: str, name: str) -> bytes:
        return reader.read_entry(_path(job_id), name)

    def set_mapping(self, job_id: str, mapping: Mapping[str, str]) -> None:
        ImportJobRecord.objects.filter(pk=job_id).update(mapping_json=dict(mapping))

    def claim(self, job_id: str) -> bool:
        """One confirmation only, however many requests arrive."""
        with transaction.atomic():
            changed = ImportJobRecord.objects.filter(
                pk=job_id, status=ImportJobRecord.Status.UPLOADED
            ).update(status=ImportJobRecord.Status.CONFIRMING)
        return changed == 1

    def finish(self, job_id: str, report: Mapping[str, Any]) -> None:
        ImportJobRecord.objects.filter(pk=job_id).update(
            status=ImportJobRecord.Status.DONE, report_json=dict(report)
        )
        _remove(job_id)


class CsvExporter:
    id = "csv"

    def write(
        self, columns: Sequence[str], rows: Sequence[Mapping[str, str]], files: Mapping[str, bytes]
    ) -> ExportedFile:
        data = writer.write_csv(columns, rows)
        if not files:
            return ExportedFile("csv", "text/csv; charset=utf-8", data)
        return ExportedFile("zip", "application/zip", writer.write_zip(data, files))
