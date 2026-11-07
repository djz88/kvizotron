"""Import from upload to report, with the real provider and media below it (AC-49, AC-51)."""

import io
import zipfile
from pathlib import Path
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import MULTIPART_CONTENT
from PIL import Image

from app.api import admin_import
from app.contracts import ALLOW_INTERNAL_IMAGE_ADDRESSES, EXTERNAL_IMAGE_MODE
from app.domain import authoring, settings
from app.domain.models import BankQuestion, Quiz, QuizRevision
from app.kernel.models import AdminUser
from app.providers.csv_io import provider as provider_module
from app.providers.csv_io.models import ImportJobRecord
from app.providers.media_local import remote
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import ADMIN_ID, make_bank, make_quiz, open_quiz_run, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
QUIZ_HEAD = (
    "row_type,title_cs,description_cs,locales,type,prompt_cs,option_1_cs,option_2_cs,correct"
)
QUIZ_ROW = "quiz,Kvíz,Popis,cs,,,,,"
GOOD = "question,,,,choice,Otázka,A,B,A"
BAD = "question,,,,choice,Vadná,A,B,Z"
URL = "https://obrazky.example/a.png"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "import" / "quiz-with-category.csv"


def csv_of(*lines, head=QUIZ_HEAD):
    return "\n".join((head, *lines)).encode()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


def zip_of(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


@pytest.fixture
def uploader(admin_user):
    client = FormClient()
    client.force_login(admin_user)
    return client


@pytest.fixture
def fetch(monkeypatch):
    fake = mock.Mock(side_effect=lambda *a, **k: png())
    monkeypatch.setattr(remote, "fetch", fake)
    return fake


def upload(client, data, target="new_quiz", name="q.csv"):
    file = SimpleUploadedFile(name, data)
    path = f"/admin/import/new?target={target}&lang=en"
    return client.post(path, {"file": file}, content_type=MULTIPART_CONTENT)


def job_url(step):
    return f"/admin/import/{ImportJobRecord.objects.get().pk}/{step}"


def imported(client, data, target="new_quiz", name="q.csv"):
    assert upload(client, data, target, name).status_code == 302
    return client.post(job_url("confirm"))


def text(response):
    return response.content.decode()


def test_clean_file_skips_mapping_and_nothing_changes_before_confirm(uploader):
    response = upload(uploader, csv_of(QUIZ_ROW, GOOD))
    assert response["Location"].endswith("/check")
    page = uploader.get(job_url("check") + "?lang=en")
    assert "Otázka" in text(page)
    assert not Quiz.objects.exists()


def test_unknown_column_opens_mapping_with_do_not_use_preselected(uploader):
    data = csv_of(
        "quiz,Kvíz,Popis,cs,,,,,,x", "question,,,,choice,Otázka,A,B,A,x", head=QUIZ_HEAD + ",nazev"
    )
    response = upload(uploader, data)
    assert response["Location"].endswith("/mapping")
    page = text(uploader.get(job_url("mapping") + "?lang=en"))
    assert "nazev" in page
    assert '<option value="" selected' in page


def test_mapping_is_used_at_check_and_confirm(uploader):
    head = QUIZ_HEAD.replace("prompt_cs", "otazka")
    upload(uploader, csv_of(QUIZ_ROW, GOOD, head=head))
    response = uploader.post(job_url("mapping"), {"map_otazka": "prompt_cs"})
    assert response["Location"].endswith("/check")
    uploader.post(job_url("confirm"))
    quiz = Quiz.objects.get()
    prompt = authoring.editable_questions(quiz)[0]["definition"]["prompt"]["cs"]
    assert prompt == "Otázka"


def test_mapping_onto_a_column_the_file_has_is_refused(uploader):
    upload(uploader, csv_of("quiz,Kvíz,Popis,cs,,,,,,x", head=QUIZ_HEAD + ",nazev"))
    response = uploader.post(job_url("mapping") + "?lang=en", {"map_nazev": "prompt_cs"})
    assert response.status_code == 200
    assert 'role="alert"' in text(response)


def test_check_lists_errors_with_row_and_column_and_shows_first_questions(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD, BAD))
    page = text(uploader.get(job_url("check") + "?lang=en"))
    assert "Vadná" not in page
    assert '<td data-label="Row">4</td>' in page
    assert "correct" in page
    assert "Otázka" in page


def test_refused_file_at_check_says_so_and_offers_no_confirm(uploader):
    upload(uploader, csv_of(GOOD))
    page = text(uploader.get(job_url("check") + "?lang=en"))
    assert 'role="alert"' in page
    assert job_url("confirm") not in page


def test_confirm_imports_good_rows_and_report_links_the_draft(uploader):
    response = imported(uploader, csv_of(QUIZ_ROW, GOOD, BAD))
    assert response["Location"].endswith("/report")
    quiz = Quiz.objects.get()
    assert len(authoring.editable_questions(quiz)) == 1
    page = text(uploader.get(job_url("report") + "?lang=en"))
    assert f"/admin/quizzes/{quiz.id}/edit" in page
    assert '<td data-label="Row">4</td>' in page


def test_double_confirm_imports_once_and_second_shows_report(uploader):
    imported(uploader, csv_of(QUIZ_ROW, GOOD))
    second = uploader.post(job_url("confirm"))
    assert second["Location"].endswith("/report")
    assert Quiz.objects.count() == 1
    assert len(authoring.editable_questions(Quiz.objects.get())) == 1


def test_import_into_draft_of_running_quiz_leaves_public_quiz_unchanged(uploader):
    run = open_quiz_run()
    quiz = run.quiz
    revision = run.current_revision_id
    data = csv_of(GOOD, head=QUIZ_HEAD)
    imported(uploader, data, target=f"draft:{quiz.id}")
    run.refresh_from_db()
    assert run.current_revision_id == revision
    assert authoring.latest_published(quiz).pk == revision
    assert len(authoring.latest_published(quiz).snapshot_json["questions"]) == 1
    assert len(authoring.editable_questions(quiz)) == 2
    assert FormClient().get(f"/q/{quiz.slug}").status_code == 200


def test_publish_is_never_called_and_no_revision_is_published(uploader):
    imported(uploader, csv_of(QUIZ_ROW, GOOD))
    assert not QuizRevision.objects.exclude(status=QuizRevision.Status.DRAFT).exists()


def test_import_into_a_bank(uploader):
    bank = make_bank()
    imported(uploader, csv_of(GOOD), target=f"bank:{bank.id}")
    assert BankQuestion.objects.filter(bank=bank).count() == 1


def test_unknown_target_is_404(logged_in):
    assert logged_in.get(f"/admin/import/new?target=draft:{ADMIN_ID}").status_code == 404
    assert logged_in.get("/admin/import/new?target=nonsense").status_code == 404


def test_archived_quiz_refuses_at_confirm_with_a_report(uploader):
    quiz = published_quiz()
    upload(uploader, csv_of(GOOD), target=f"draft:{quiz.id}")
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    uploader.post(job_url("confirm"))
    assert 'role="alert"' in text(uploader.get(job_url("report") + "?lang=en"))
    assert len(authoring.editable_questions(quiz)) == 1


def image_row(image):
    head = QUIZ_HEAD + ",image,image_alt_cs"
    return csv_of("quiz,Kvíz,Popis,cs,,,,,,,", f"{GOOD},{image},Popis", head=head)


def test_failed_address_keeps_question_warns_and_blocks_publish_in_copy_mode(uploader, monkeypatch):
    monkeypatch.setattr(remote, "fetch", mock.Mock(side_effect=remote.RemoteRefused("down")))
    imported(uploader, image_row(URL))
    quiz = Quiz.objects.get()
    image = authoring.editable_questions(quiz)[0]["definition"]["image"]
    assert image["asset"] is None
    assert image["source"] == URL
    assert URL in text(uploader.get(job_url("report") + "?lang=en"))
    assert any(p.code == "image_no_copy" for p in authoring.validate_for_publication(quiz))


def test_address_makes_a_copy_and_stays_as_the_source(uploader, fetch):
    imported(uploader, image_row(URL))
    image = authoring.editable_questions(Quiz.objects.get())[0]["definition"]["image"]
    assert image["asset"]
    assert image["source"] == URL
    assert fetch.call_count == 1


def test_same_address_in_two_rows_is_fetched_once(uploader, fetch):
    head = QUIZ_HEAD + ",image,image_alt_cs"
    data = csv_of("quiz,Kvíz,Popis,cs,,,,,,,", f"{GOOD},{URL},x", f"{GOOD},{URL},x", head=head)
    imported(uploader, data)
    assert fetch.call_count == 1


def test_internal_address_never_fetched_with_switch_off(uploader, monkeypatch):
    create = mock.Mock(side_effect=remote.RemoteInternal("internal"))
    monkeypatch.setattr(remote, "fetch", create)
    settings.set_global(ALLOW_INTERNAL_IMAGE_ADDRESSES, "off", admin_id=ADMIN_ID)
    imported(uploader, image_row("https://192.168.1.1/a.png"))
    assert create.call_args.kwargs["allow_internal"] is False
    assert (
        authoring.editable_questions(Quiz.objects.get())[0]["definition"]["image"]["asset"] is None
    )


def test_fetches_share_the_budget_and_the_rest_counts_as_failed(uploader, fetch, monkeypatch):
    monkeypatch.setattr(admin_import, "FETCHES_SECONDS", -1.0)
    imported(uploader, image_row(URL))
    assert fetch.call_count == 0
    image = authoring.editable_questions(Quiz.objects.get())[0]["definition"]["image"]
    assert image["asset"] is None
    assert URL in text(uploader.get(job_url("report") + "?lang=en"))


def test_budget_is_that_of_adr_0043():
    assert admin_import.FETCHES_SECONDS == 25.0


def test_fetching_happens_at_confirm_never_at_check(uploader, fetch):
    upload(uploader, image_row(URL))
    uploader.get(job_url("check"))
    assert fetch.call_count == 0
    uploader.post(job_url("confirm"))
    assert fetch.call_count == 1


def test_zip_image_is_stored_and_a_bad_one_is_a_row_error_in_the_report(uploader):
    head = QUIZ_HEAD + ",image,image_alt_cs"
    data = csv_of(
        "quiz,Kvíz,Popis,cs,,,,,,,",
        f"{GOOD},good.png,Popis",
        "question,,,,choice,Vadný obrázek,A,B,A,bad.png,Popis",
        head=head,
    )
    upload_data = zip_of({"q.csv": data, "good.png": png(), "bad.png": b"this is no image"})
    response = imported(uploader, upload_data, name="q.zip")
    assert response.status_code == 302
    questions = authoring.editable_questions(Quiz.objects.get())
    assert len(questions) == 1
    image = questions[0]["definition"]["image"]
    assert MediaAsset.objects.filter(pk=image["asset"]).exists()
    assert "source" not in image
    assert '<td data-label="Row">4</td>' in text(uploader.get(job_url("report") + "?lang=en"))


def test_missing_zip_file_is_a_row_error_at_check(uploader):
    upload(uploader, image_row("missing.png"))
    page = text(uploader.get(job_url("check") + "?lang=en"))
    assert "missing.png" in page


def test_unconfirmed_import_stores_no_media(uploader):
    head = QUIZ_HEAD + ",image,image_alt_cs"
    data = csv_of("quiz,Kvíz,Popis,cs,,,,,,,", f"{GOOD},good.png,Popis", head=head)
    upload(uploader, zip_of({"q.csv": data, "good.png": png()}), name="q.zip")
    uploader.get(job_url("check"))
    assert not MediaAsset.objects.exists()


def test_external_mode_keeps_no_extra_rule(uploader, fetch):
    head = QUIZ_HEAD + f",setting_{EXTERNAL_IMAGE_MODE},image,image_alt_cs"
    data = csv_of("quiz,Kvíz,Popis,cs,,,,,,external,,", f"{GOOD},,{URL},x", head=head)
    imported(uploader, data)
    quiz = Quiz.objects.get()
    assert settings.quiz_override(EXTERNAL_IMAGE_MODE, quiz) == "external"
    assert authoring.editable_questions(quiz)[0]["definition"]["image"]["asset"]


def test_refused_file_returns_to_upload_with_message(uploader):
    response = upload(uploader, "a\nč".encode("cp1250"))
    assert response.status_code == 200
    assert "UTF-8" in text(response)
    assert not ImportJobRecord.objects.exists()


def test_upload_without_a_file_asks_for_one(uploader):
    response = uploader.post("/admin/import/new?target=new_quiz&lang=en", {})
    assert response.status_code == 200
    assert 'role="alert"' in text(response)


def test_expired_job_says_so(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    url = job_url("check")
    ImportJobRecord.objects.update(expires_at="2020-01-01T00:00:00Z")
    page = uploader.get(url + "?lang=en")
    assert page.status_code == 404
    assert "no longer available" in text(page)


def test_other_admins_job_is_not_reachable(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    other = FormClient()
    other.force_login(AdminUser.objects.create_admin("bob", "dlouhe-a-neobvykle-heslo"))
    assert other.get(job_url("check")).status_code == 404
    assert other.post(job_url("confirm")).status_code == 404
    assert not Quiz.objects.exists()


def test_buttons_hidden_and_pages_404_without_provider(logged_in, monkeypatch):
    quiz = make_quiz()
    bank = make_bank()
    pages = {
        "/admin/quizzes": True,
        f"/admin/quizzes/{quiz.id}/edit": True,
        f"/admin/banks/{bank.id}": True,
    }
    for path in pages:
        assert "/admin/import/new" in text(logged_in.get(path))
    monkeypatch.setattr("app.api.rendering.importer", lambda: None)
    for path in pages:
        assert "/admin/import/new" not in text(logged_in.get(path))
    assert logged_in.get("/admin/import/new?target=new_quiz").status_code == 404


def test_login_required_on_every_step(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    anonymous = FormClient()
    assert anonymous.get("/admin/import/new?target=new_quiz").status_code == 302
    for step in ("mapping", "check", "report"):
        assert anonymous.get(job_url(step)).status_code == 302
    assert anonymous.post(job_url("confirm")).status_code == 302
    assert not Quiz.objects.exists()


def test_confirm_requires_post(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    assert uploader.get(job_url("confirm")).status_code == 405


SAMPLE_FILE = Path(provider_module.__file__).parent / "sample" / "quiz-sample.csv"


def test_sample_imports_with_no_errors_no_warnings_and_no_mapping(uploader):
    response = upload(uploader, SAMPLE_FILE.read_bytes())
    assert response["Location"].endswith("/check")
    uploader.post(job_url("confirm"))
    report = text(uploader.get(job_url("report") + "?lang=en"))
    assert "Rows that were skipped" not in report
    assert "Warnings" not in report
    quiz = Quiz.objects.get()
    assert quiz.supported_locales == ["cs", "en", "uk"]
    assert len(authoring.editable_questions(quiz)) == 5
    assert not authoring.validate_for_publication(quiz)


def test_fixture_with_category_reports_it_after_one_click(uploader):
    response = upload(uploader, FIXTURE.read_bytes())
    assert response["Location"].endswith("/mapping")
    uploader.post(job_url("mapping"), {})
    uploader.post(job_url("confirm"))
    report = text(uploader.get(job_url("report") + "?lang=en"))
    assert "category_cs" in report
    question = authoring.editable_questions(Quiz.objects.get())[1]
    assert len(question["definition"]["correct"]) == 3


def test_upload_page_links_both_and_they_download(logged_in):
    page = text(logged_in.get("/admin/import/new?target=new_quiz"))
    assert "/admin/import/sample.csv" in page
    assert "/admin/import/format.md" in page
    assert logged_in.get("/admin/import/sample.csv")["Content-Disposition"].startswith("attachment")
    assert b"schema_version" in logged_in.get("/admin/import/format.md").content


def test_sample_and_format_require_login():
    client = FormClient()
    assert client.get("/admin/import/sample.csv").status_code == 302
    assert client.get("/admin/import/format.md").status_code == 302


def test_finished_import_check_and_mapping_go_to_the_report(uploader):
    imported(uploader, csv_of(QUIZ_ROW, GOOD))
    for step in ("check", "mapping"):
        response = uploader.get(job_url(step))
        assert response.status_code == 302
        assert response["Location"].endswith("/report")


def test_job_whose_file_is_gone_says_so(uploader, media_path, tmp_path):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    (tmp_path / "imports" / str(ImportJobRecord.objects.get().pk)).unlink()
    page = uploader.get(job_url("check") + "?lang=en")
    assert page.status_code == 404
    assert "no longer available" in text(page)


def test_failure_after_claim_reports_and_does_not_stick(uploader, monkeypatch):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    broken = mock.Mock(side_effect=RuntimeError("unexpected"))
    monkeypatch.setattr(admin_import.question_import, "apply", broken)
    response = uploader.post(job_url("confirm"))
    assert response["Location"].endswith("/report")
    assert "did not finish" in text(uploader.get(job_url("report") + "?lang=en"))
    assert not Quiz.objects.exists()


def test_bank_deleted_before_confirm_reports(uploader):
    bank = make_bank()
    upload(uploader, csv_of(GOOD), target=f"bank:{bank.id}")
    bank.delete()
    response = uploader.post(job_url("confirm"))
    assert response["Location"].endswith("/report")
    assert "did not finish" in text(uploader.get(job_url("report") + "?lang=en"))


def test_report_while_the_first_request_runs_says_wait(uploader):
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    ImportJobRecord.objects.update(status=ImportJobRecord.Status.CONFIRMING)
    response = uploader.post(job_url("confirm"))
    assert response["Location"].endswith("/report")
    page = text(uploader.get(job_url("report") + "?lang=en"))
    assert "still running" in page
    assert not Quiz.objects.exists()
