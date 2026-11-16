"""The results export page, its background job and the downloads (AC-101 to AC-107)."""

import io
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from app.api import export_runner
from app.domain import attempts, authoring, results_export, retention, settings
from app.domain.models import Participant, Quiz
from app.kernel.models import AdminUser, AuditEvent
from app.providers.csv_io.models import ExportJobRecord
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz
from tests.support.client import FormClient
from tests.support.photos import Player, photo_quiz, run_of, upload

pytestmark = pytest.mark.django_db
NEW = "/admin/exports/new"


@pytest.fixture(autouse=True)
def synchronous(monkeypatch, settings, tmp_path):
    """The job runs inside the request, so a test sees it finished."""
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    monkeypatch.setattr(export_runner, "SPAWN", lambda target: target())
    return tmp_path


def text(response):
    return response.content.decode()


def body(response):
    return b"".join(response.streaming_content)


def a_quiz(slug="vysledky", profile="answers"):
    quiz = make_quiz(slug)
    add_question(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, profile, admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def play(run, number=1):
    who = Participant.objects.create(run=run, anonymous_key_hash=f"h{number}", display_name="Jana")
    started = attempts.start(run, participant=who)
    question = attempts.questions_of(started.attempt)[0]["id"]
    attempts.submit(
        started.attempt.id, started.token, {question: {"options": [OPTION_A]}}, f"k-{number:010d}"
    )


def played_run(slug="vysledky"):
    quiz = a_quiz(slug)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    play(run)
    return quiz, run


def export(client, quiz, runs=None, **fields):
    query = f"?quiz={quiz.id}" + (f"&runs={','.join(str(r.id) for r in runs)}" if runs else "")
    return client.post(NEW + query, fields)


def last_job():
    return ExportJobRecord.objects.order_by("-created_at").first()


def test_page_lists_only_offered_files(logged_in):
    """AC-101."""
    quiz = a_quiz(profile="none")
    first = authoring.open_run(quiz, admin_id=ADMIN_ID)
    authoring.close_run(first, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{NEW}?quiz={quiz.id}&runs={first.id}"))
    assert 'value="questions"' in html
    assert 'value="attempts"' not in html and 'value="answers"' not in html

    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{NEW}?quiz={quiz.id}"))
    assert 'value="attempts"' in html and 'value="questions"' in html
    assert "1 z 2" in html


def test_personal_needs_confirmation(logged_in):
    """AC-107."""
    quiz, run = played_run()
    refused = export(logged_in, quiz, [run], files="attempts", bundle="separate")
    assert refused.status_code == 400
    assert not ExportJobRecord.objects.exists()

    sent = export(logged_in, quiz, [run], files="attempts", bundle="separate", personal_ok="on")
    assert sent.status_code == 302
    event = AuditEvent.objects.get(action="export.created")
    assert event.details_json["personal"] is True
    assert "Jana" not in str(event.details_json)


def test_download_csv_end_to_end(logged_in):
    """AC-102."""
    quiz, run = played_run()
    export(logged_in, quiz, [run], files="attempts", bundle="separate", personal_ok="on")
    job = last_job()
    assert job.status == "done"
    (name,) = job.report_json["files"]
    assert name.endswith("-attempts.csv") and name.startswith("vysledky-run-1-")

    jobs = text(logged_in.get("/admin/exports/jobs"))
    assert f"/admin/exports/{job.pk}/{name}" in jobs

    response = logged_in.get(f"/admin/exports/{job.pk}/{name}")
    assert response.status_code == 200
    data = body(response).decode("utf-8")
    assert data.startswith("﻿Běh;Revize;ID pokusu")
    assert "\r\n" in data and "Jana" in data
    assert response["Content-Disposition"].startswith("attachment")
    assert name in response["Content-Disposition"]
    assert "no-store" in response["Cache-Control"]
    downloaded = AuditEvent.objects.get(action="export.downloaded")
    assert downloaded.entity_id == str(job.pk)


def photo_run(media):
    quiz = photo_quiz(slug="foto")
    run = run_of(quiz)
    player = Player(run)
    player.submit({f"{player.question('image_answer')}:image": upload()})
    return quiz, run, player.attempt


def zip_of(client):
    job = last_job()
    assert job.status == "done", job.report_json
    (name,) = job.report_json["files"]
    assert name.endswith(".zip")
    archive = zipfile.ZipFile(io.BytesIO(body(client.get(f"/admin/exports/{job.pk}/{name}"))))
    answers = next(n for n in archive.namelist() if n.endswith("-answers.csv"))
    return archive, archive.read(answers).decode("utf-8")


def test_zip_with_and_without_photos(logged_in, synchronous):
    """AC-104."""
    quiz, run, attempt = photo_run(synchronous)
    path = f"photos/1/{attempt.id}-1.webp"
    page = text(logged_in.get(f"{NEW}?quiz={quiz.id}"))
    assert 'name="photos"' in page

    export(logged_in, quiz, None, files="answers", bundle="zip", photos="on", personal_ok="on")
    archive, answers = zip_of(logged_in)
    assert path in archive.namelist()
    assert path in answers

    export(logged_in, quiz, None, files="answers", bundle="zip", personal_ok="on")
    archive, answers = zip_of(logged_in)
    assert not [n for n in archive.namelist() if n.startswith("photos/")]
    assert path in answers


def test_photos_only_with_answers_and_count_as_personal(logged_in, synchronous):
    """AC-104, AC-107: photos come with the answers file and need the confirmation."""
    quiz, run, attempt = photo_run(synchronous)

    sent = export(logged_in, quiz, None, files="questions", bundle="zip", photos="on")
    assert sent.status_code == 302
    job = last_job()
    assert job.choices_json["photos"] is False
    archive = zipfile.ZipFile(
        io.BytesIO(body(logged_in.get(f"/admin/exports/{job.pk}/{job.report_json['files'][0]}")))
    )
    assert not [n for n in archive.namelist() if n.startswith("photos/")]
    created = AuditEvent.objects.get(action="export.created")
    assert created.details_json["personal"] is False

    refused = export(logged_in, quiz, None, files="answers", bundle="zip", photos="on")
    assert refused.status_code == 400
    assert ExportJobRecord.objects.count() == 1

    export(logged_in, quiz, None, files="answers", bundle="zip", photos="on", personal_ok="on")
    event = AuditEvent.objects.filter(action="export.created").order_by("-pk").first()
    assert event.details_json["photos"] is True
    assert event.details_json["personal"] is True


def test_photos_count_as_personal_in_the_audit():
    """AC-107: a ZIP with photos is personal even when every chosen file alone is not."""
    results_export.record_created("job", ADMIN_ID, {"files": ["questions"], "photos": True})
    event = AuditEvent.objects.get(action="export.created")
    assert event.details_json["personal"] is True


def test_job_files_render_as_a_list(logged_in):
    """Long file names wrap on a phone: each one is a list item."""
    quiz, run = played_run()
    export(logged_in, quiz, [run], files="attempts", bundle="separate", personal_ok="on")
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    jobs = text(logged_in.get("/admin/exports/jobs"))
    assert '<ul class="export-files">' in jobs
    assert jobs.count('<li><a href="/admin/exports/') == 2


def test_create_rolls_back_without_the_audit(logged_in, monkeypatch):
    """The job and its audit event are written together, or neither is."""
    quiz, run = played_run()

    def broken(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(results_export, "record_created", broken)
    with pytest.raises(RuntimeError):
        export(logged_in, quiz, [run], files="questions", bundle="separate")
    assert not ExportJobRecord.objects.exists()


def test_missing_photo_skipped(logged_in, synchronous):
    quiz, run, attempt = photo_run(synchronous)
    for asset in MediaAsset.objects.all():
        (Path(synchronous) / asset.storage_key).unlink(missing_ok=True)
    export(logged_in, quiz, None, files="answers", bundle="zip", photos="on", personal_ok="on")
    archive, answers = zip_of(logged_in)
    assert not [n for n in archive.namelist() if n.startswith("photos/")]


def test_download_other_admin_404(logged_in):
    """AC-105."""
    quiz, run = played_run()
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    job = last_job()
    (name,) = job.report_json["files"]
    address = f"/admin/exports/{job.pk}/{name}"
    assert logged_in.get(address).status_code == 200

    other = FormClient()
    other.force_login(AdminUser.objects.create_admin("bob", "jine-dlouhe-heslo-pro-boba"))
    assert other.get(address).status_code == 404
    assert str(job.pk) not in text(other.get("/admin/exports/jobs"))

    ExportJobRecord.objects.filter(pk=job.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert logged_in.get(address).status_code == 404


def test_restart_interrupted(logged_in):
    """AC-106."""
    quiz, run = played_run()
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    old = last_job()
    ExportJobRecord.objects.filter(pk=old.pk).update(status="interrupted")
    assert "/restart" in text(logged_in.get("/admin/exports/jobs"))

    response = logged_in.post(f"/admin/exports/{old.pk}/restart")
    assert response.status_code == 302
    assert not ExportJobRecord.objects.filter(pk=old.pk).exists()
    new = last_job()
    assert new.status == "done"
    assert new.choices_json["files"] == ["questions"]


def test_restart_after_the_data_went_exports_only_the_submitted_count(
    logged_in, monkeypatch, synchronous
):
    """AC-111: a job stopped by the deletion, restarted, holds the count and nobody's name."""
    quiz, run = played_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    monkeypatch.setattr(export_runner, "SPAWN", lambda target: None)
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    stopped = last_job()
    assert stopped.status == "running"

    assert retention.purge_run(run, trigger="automatic", admin_id=None) is True

    stopped.refresh_from_db()
    assert stopped.status == "failed"
    assert stopped.report_json["error"] == "run_data_deleted"

    monkeypatch.setattr(export_runner, "SPAWN", lambda target: target())
    assert logged_in.post(f"/admin/exports/{stopped.pk}/restart").status_code == 302

    new = last_job()
    assert new.pk != stopped.pk
    assert new.status == "done"
    (name,) = new.report_json["files"]
    lines = body(logged_in.get(f"/admin/exports/{new.pk}/{name}")).decode("utf-8").splitlines()
    assert len(lines) == 2
    row = dict(zip(lines[0].lstrip("\ufeff").split(";"), lines[1].split(";"), strict=True))
    assert row["Běh"] == "1"
    assert row["Odeslané pokusy"] == "1"
    assert "Jana" not in "".join(lines)


def test_restart_refused_for_a_done_job(logged_in):
    """AC-106."""
    quiz, run = played_run()
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    done = last_job()
    assert done.status == "done"
    assert logged_in.post(f"/admin/exports/{done.pk}/restart").status_code == 404
    assert ExportJobRecord.objects.count() == 1


def test_thread_that_cannot_start_frees_the_slot(logged_in, monkeypatch):
    quiz, run = played_run()

    def refuse(target):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(export_runner, "SPAWN", refuse)
    export(logged_in, quiz, [run], files="questions", bundle="separate")
    job = last_job()
    assert (job.status, job.report_json["error"]) == ("failed", "error")


def test_refused_form_keeps_the_choices(logged_in, synchronous):
    quiz, run, attempt = photo_run(synchronous)
    first = text(logged_in.get(f"{NEW}?quiz={quiz.id}"))
    assert 'name="photos" value="on" checked' in first
    assert 'name="bundle" value="zip">' in first  # the main button until the admin picks

    response = export(logged_in, quiz, None, files="answers", bundle="separate")
    assert response.status_code == 400  # personal data not confirmed
    html = text(response)
    assert 'value="answers" checked' in html
    assert 'value="questions" checked' not in html
    assert 'name="photos" value="on" checked' not in html
    assert 'name="bundle" value="separate">' in html
    assert 'name="bundle" value="zip" class="secondary">' in html


def test_foreign_run_refused(logged_in):
    quiz = a_quiz("prvni")
    other_quiz, other_run = played_run("druhy")
    address = f"{NEW}?quiz={quiz.id}&runs={other_run.id}"
    assert logged_in.get(address).status_code == 404
    assert logged_in.post(address, {"files": "questions", "bundle": "zip"}).status_code == 404
    assert logged_in.get(f"{NEW}?quiz=nic").status_code == 404
    assert not ExportJobRecord.objects.exists()
    assert Quiz.objects.count() == 2


def test_entry_points_link_to_export(logged_in):
    quiz, run = played_run()
    run_page = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert f"{NEW}?quiz={quiz.id}&amp;runs={run.id}" in run_page
    header = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f"{NEW}?quiz={quiz.id}" in header
    runs_page = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    assert f'action="{NEW}"' in runs_page
    assert f'name="runs" value="{run.id}"' in runs_page
