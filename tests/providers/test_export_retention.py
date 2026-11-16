"""What deleting a run's data asks of the export jobs and the media files (D3)."""

import os
import shutil
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from app.contracts import ExportTable
from app.providers.csv_io.models import ExportJobRecord
from app.providers.csv_io.results import BOOT, CsvResultsExporter
from app.providers.media_local.models import MediaAsset
from app.providers.media_local.provider import LocalMediaStorage

pytestmark = pytest.mark.django_db

QUIZ = "quiz-1"
OTHER_QUIZ = "quiz-2"
RUN = "run-1"
OTHER_RUN = "run-2"


@pytest.fixture
def exporter(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return CsvResultsExporter()


def _job(tmp_path, status, choices):
    now = timezone.now()
    job = ExportJobRecord.objects.create(
        admin_id="a",
        kind="results",
        status=status,
        choices_json=choices,
        report_json={"files": ["attempts.csv"], "error": None},
        boot="x",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    directory = tmp_path / "exports" / str(job.pk)
    directory.mkdir(parents=True)
    (directory / "attempts.csv").write_text("x")
    return job, directory


def _table():
    return [ExportTable("attempts", ["run"], ["Run"], [{"run": "1"}])]


def test_a_done_job_naming_the_run_loses_row_and_directory(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})

    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def test_a_done_job_of_all_runs_of_the_quiz_goes_too(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [], "all_runs": True})

    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def test_a_job_of_another_quiz_stays(exporter, tmp_path):
    job, directory = _job(
        tmp_path, "done", {"quiz": OTHER_QUIZ, "runs": [OTHER_RUN], "all_runs": True}
    )

    exporter.delete_for_runs(QUIZ, [RUN])

    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()


def test_a_job_of_the_same_quiz_naming_other_runs_stays(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [OTHER_RUN], "all_runs": False})

    exporter.delete_for_runs(QUIZ, [RUN])

    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_a_finished_job_that_did_not_succeed_goes_too(exporter, tmp_path, status):
    job, directory = _job(tmp_path, status, {"quiz": QUIZ, "runs": [RUN], "all_runs": False})

    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_an_unfinished_job_fails_and_a_later_write_leaves_no_files(exporter, tmp_path, status):
    job, directory = _job(tmp_path, status, {"quiz": QUIZ, "runs": [RUN], "all_runs": False})

    exporter.delete_for_runs(QUIZ, [RUN])

    job.refresh_from_db()
    assert job.status == "failed"
    assert job.report_json == {"files": [], "error": "run_data_deleted"}
    assert not directory.exists()

    exporter.write(str(job.pk), _table(), {}, bundle=False)

    job.refresh_from_db()
    assert job.status == "failed"
    assert not directory.exists()


def test_a_job_stopped_by_a_deletion_stays_restartable_when_called_again(exporter, tmp_path):
    job, directory = _job(tmp_path, "running", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})

    exporter.delete_for_runs(QUIZ, [RUN])
    exporter.delete_for_runs(QUIZ, [RUN])

    job.refresh_from_db()
    assert job.status == "failed"
    assert job.report_json == {"files": [], "error": "run_data_deleted"}
    assert not directory.exists()


def test_a_failed_job_of_another_cause_still_goes_when_called_again(exporter, tmp_path):
    job, directory = _job(tmp_path, "failed", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})
    ExportJobRecord.objects.filter(pk=job.pk).update(report_json={"files": [], "error": "error"})

    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def test_files_that_cannot_be_removed_raise_and_keep_the_row_for_a_retry(
    exporter, tmp_path, monkeypatch
):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})
    real = shutil.rmtree

    def refuse(_path, **_kwargs):
        raise OSError("disk")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    with pytest.raises(OSError):
        exporter.delete_for_runs(QUIZ, [RUN])
    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()

    monkeypatch.setattr(shutil, "rmtree", real)
    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_directory_that_cannot_be_reached_raises_and_keeps_the_row(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})
    parent = directory.parent
    parent.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            exporter.delete_for_runs(QUIZ, [RUN])
    finally:
        parent.chmod(0o700)

    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()


def test_a_job_whose_directory_is_already_gone_is_deleted(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})
    shutil.rmtree(directory)

    exporter.delete_for_runs(QUIZ, [RUN])

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()


def test_a_failed_job_is_not_claimed_again(exporter, tmp_path):
    job, _directory = _job(tmp_path, "queued", {"quiz": QUIZ, "runs": [RUN], "all_runs": False})
    ExportJobRecord.objects.filter(pk=job.pk).update(boot=BOOT)

    exporter.delete_for_runs(QUIZ, [RUN])

    assert exporter.claim_next() is None


def test_nothing_named_changes_nothing(exporter, tmp_path):
    job, directory = _job(tmp_path, "done", {"quiz": QUIZ, "runs": [RUN], "all_runs": True})

    exporter.delete_for_runs(QUIZ, [])

    assert ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert directory.exists()


def _asset(*, private, age):
    asset_id = uuid4()
    MediaAsset.objects.create(
        id=asset_id,
        storage_key=f"{asset_id}.webp",
        mime_type="image/webp",
        size=1,
        sha256="0" * 64,
        private=private,
    )
    MediaAsset.objects.filter(pk=asset_id).update(created_at=timezone.now() - age)
    return str(asset_id)


def test_private_assets_older_than_finds_only_old_private_ones():
    old_private = _asset(private=True, age=timedelta(hours=2))
    _asset(private=True, age=timedelta(minutes=10))
    _asset(private=False, age=timedelta(hours=2))

    found = LocalMediaStorage().private_assets_older_than(timezone.now() - timedelta(hours=1))

    assert list(found) == [old_private]
