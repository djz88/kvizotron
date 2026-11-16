"""Background results export jobs of the CSV provider."""

import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from app.contracts import ExportJobGone, ExportTable
from app.providers.csv_io.models import ExportJobRecord
from app.providers.csv_io.results import CsvResultsExporter

pytestmark = pytest.mark.django_db


@pytest.fixture
def exporter(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return CsvResultsExporter()


def _tables():
    return [
        ExportTable("attempts", ["run", "score"], ["Run", "Score"], [{"run": "1", "score": "2,5"}]),
        ExportTable("answers", ["run", "text"], ["Run", "Text"], [{"run": "1", "text": "=x"}]),
    ]


def test_create_purges_expired(exporter, tmp_path):
    now = timezone.now()
    old = ExportJobRecord.objects.create(
        admin_id="a",
        kind="results",
        status="done",
        choices_json={},
        report_json={"files": ["attempts.csv"], "error": None},
        boot="x",
        created_at=now - timedelta(hours=25),
        expires_at=now - timedelta(hours=1),
    )
    directory = tmp_path / "exports" / str(old.pk)
    directory.mkdir(parents=True)
    (directory / "attempts.csv").write_text("x")

    exporter.create("a", {"run": 1})

    assert not ExportJobRecord.objects.filter(pk=old.pk).exists()
    assert not directory.exists()


def test_slots(exporter):
    """AC-105."""
    a1 = exporter.create("A", {"n": 1})
    exporter.create("A", {"n": 2})
    b1 = exporter.create("B", {"n": 3})

    assert exporter.claim_next().id == a1
    assert exporter.claim_next().id == b1
    assert exporter.claim_next() is None


def test_write_separate_and_bundle(exporter, tmp_path):
    """AC-105."""
    job_id = exporter.create("A", {})
    assert exporter.claim_next().id == job_id
    exporter.write(job_id, _tables(), {}, bundle=False)

    view = exporter.job(job_id, "A")
    assert view.status == "done"
    assert list(view.files) == ["attempts.csv", "answers.csv"]
    attempts = Path(exporter.path(job_id, "A", "attempts.csv"))
    assert attempts.read_bytes().startswith("﻿Run;Score\r\n".encode())
    assert attempts.stat().st_mode & 0o777 == 0o640
    assert "'=x" in Path(exporter.path(job_id, "A", "answers.csv")).read_text(encoding="utf-8")

    photo = tmp_path / "photo.webp"
    photo.write_bytes(b"RIFF")
    bundle_id = exporter.create("B", {})
    assert exporter.claim_next().id == bundle_id
    exporter.write(
        bundle_id,
        _tables(),
        {"photos/1/x-2.webp": str(photo), "photos/1/gone.webp": str(tmp_path / "missing")},
        bundle=True,
    )

    view = exporter.job(bundle_id, "B")
    assert list(view.files) == ["results.zip"]
    with zipfile.ZipFile(exporter.path(bundle_id, "B", "results.zip")) as archive:
        assert set(archive.namelist()) == {"attempts.csv", "answers.csv", "photos/1/x-2.webp"}
        assert archive.read("photos/1/x-2.webp") == b"RIFF"
        assert archive.read("attempts.csv").startswith("﻿Run;Score".encode())


def test_write_uses_name_prefix(exporter):
    """AC-105."""
    choices = {"name": "kviz-run-1-20261109-1405"}
    job_id = exporter.create("A", choices)
    exporter.claim_next()
    exporter.write(job_id, _tables(), {}, bundle=False)
    assert list(exporter.job(job_id, "A").files) == [
        "kviz-run-1-20261109-1405-attempts.csv",
        "kviz-run-1-20261109-1405-answers.csv",
    ]
    with pytest.raises(ExportJobGone):
        exporter.path(job_id, "A", "attempts.csv")

    zip_id = exporter.create("B", choices)
    exporter.claim_next()
    exporter.write(zip_id, _tables(), {}, bundle=True)
    assert list(exporter.job(zip_id, "B").files) == ["kviz-run-1-20261109-1405.zip"]
    with zipfile.ZipFile(exporter.path(zip_id, "B", "kviz-run-1-20261109-1405.zip")) as archive:
        assert set(archive.namelist()) == {
            "kviz-run-1-20261109-1405-attempts.csv",
            "kviz-run-1-20261109-1405-answers.csv",
        }


def test_stale_jobs_become_interrupted(exporter):
    """AC-106."""
    now = timezone.now()
    stale = ExportJobRecord.objects.create(
        admin_id="A",
        kind="results",
        status="running",
        choices_json={"run": 7},
        report_json={"files": [], "error": None},
        boot="old",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )

    [view] = exporter.jobs("A")
    assert view.id == str(stale.pk)
    assert view.status == "interrupted"

    new_id = exporter.restart(str(stale.pk), "A")
    new = exporter.job(new_id, "A")
    assert new.status == "queued"
    assert dict(new.choices) == {"run": 7}
    claimed = exporter.claim_next()
    assert (claimed.id, claimed.status, dict(claimed.choices)) == (new_id, "running", {"run": 7})


def test_restart_only_interrupted_or_failed(exporter):
    """AC-106."""
    job_id = exporter.create("A", {"n": 1})
    with pytest.raises(ExportJobGone):  # queued
        exporter.restart(job_id, "A")
    exporter.claim_next()
    exporter.write(job_id, _tables(), {}, bundle=False)
    with pytest.raises(ExportJobGone):  # done
        exporter.restart(job_id, "A")
    assert ExportJobRecord.objects.count() == 1

    failed = exporter.create("A", {"n": 2})
    exporter.claim_next()
    exporter.fail(failed, "error")
    new_id = exporter.restart(failed, "A")
    assert [view.id for view in exporter.jobs("A")] == [new_id, job_id]


def test_job_belongs_to_admin(exporter):
    """AC-105."""
    job_id = exporter.create("A", {})
    exporter.claim_next()
    exporter.write(job_id, _tables(), {}, bundle=False)

    with pytest.raises(ExportJobGone):
        exporter.job(job_id, "other")
    with pytest.raises(ExportJobGone):
        exporter.path(job_id, "other", "attempts.csv")
    with pytest.raises(ExportJobGone):
        exporter.path(job_id, "A", "../x")
    with pytest.raises(ExportJobGone):
        exporter.restart(job_id, "other")
    with pytest.raises(ExportJobGone):
        exporter.job("not-a-uuid", "A")


def test_fail_records_code_and_frees_the_slot(exporter):
    """AC-105."""
    job_id = exporter.create("A", {})
    second = exporter.create("A", {})
    exporter.claim_next()
    exporter.fail(job_id, "too_large")
    view = exporter.job(job_id, "A")
    assert (view.status, view.error, list(view.files)) == ("failed", "too_large", [])
    assert exporter.claim_next().id == second


def test_jobs_newest_first_and_only_own(exporter):
    first = exporter.create("A", {})
    second = exporter.create("A", {})
    exporter.create("B", {})
    assert [view.id for view in exporter.jobs("A")] == [second, first]
    view = exporter.jobs("A")[0]
    assert view.expires_at - view.created_at == timedelta(hours=24)


def test_files_never_world_readable(exporter, tmp_path):
    """The directory is 0o750 and every file is created 0o640, before a byte is written."""
    for bundle in (False, True):
        job_id = exporter.create("A", {})
        exporter.claim_next()
        exporter.write(job_id, _tables(), {}, bundle=bundle)
        directory = tmp_path / "exports" / job_id
        assert directory.stat().st_mode & 0o777 == 0o750
        for name in exporter.job(job_id, "A").files:
            assert (directory / name).stat().st_mode & 0o777 == 0o640


def test_files_created_with_owner_only_mode(exporter, monkeypatch):
    """Each output file is opened with mode 0o640, not created first and chmod-ed later."""
    import os

    modes = []
    real_open = os.open

    def spying(path, flags, mode=0o777, *args, **kwargs):
        if "exports" in str(path):
            modes.append(mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spying)
    for bundle in (False, True):
        job_id = exporter.create("A", {})
        exporter.claim_next()
        exporter.write(job_id, _tables(), {}, bundle=bundle)
    assert modes == [0o640, 0o640, 0o640]


def test_write_after_restart_leaves_nothing(exporter, tmp_path):
    """A job no longer running (deleted or failed meanwhile) keeps no files on disk."""
    job_id = exporter.create("A", {})
    exporter.claim_next()
    ExportJobRecord.objects.filter(pk=job_id).update(status="interrupted")
    exporter.write(job_id, _tables(), {}, bundle=False)
    assert exporter.job(job_id, "A").status == "interrupted"
    assert not (tmp_path / "exports" / job_id).exists()

    gone = exporter.create("A", {})
    exporter.claim_next()
    ExportJobRecord.objects.filter(pk=gone).delete()
    exporter.write(gone, _tables(), {}, bundle=True)
    assert not (tmp_path / "exports" / gone).exists()


def test_fail_changes_only_a_running_job(exporter):
    job_id = exporter.create("A", {})
    exporter.claim_next()
    exporter.write(job_id, _tables(), {}, bundle=False)
    exporter.fail(job_id, "error")
    view = exporter.job(job_id, "A")
    assert view.status == "done"
    assert Path(exporter.path(job_id, "A", "attempts.csv")).exists()


def test_unsafe_name_refused(exporter, tmp_path):
    job_id = exporter.create("A", {"name": "../evil"})
    exporter.claim_next()
    with pytest.raises(ValueError):
        exporter.write(job_id, _tables(), {}, bundle=False)
    assert not (tmp_path / "exports" / job_id / "evil-attempts.csv").exists()
    assert not (tmp_path / "evil-attempts.csv").exists()


def test_queued_job_of_old_boot_becomes_interrupted(exporter):
    """AC-106."""
    now = timezone.now()
    stale = ExportJobRecord.objects.create(
        admin_id="A",
        kind="results",
        status="queued",
        choices_json={},
        report_json={"files": [], "error": None},
        boot="old",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    assert exporter.claim_next() is None
    assert exporter.job(str(stale.pk), "A").status == "interrupted"
