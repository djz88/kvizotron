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
from app.domain import authoring, bank_folders, settings
from app.domain.models import BankQuestion, Quiz, QuizRevision
from app.kernel.models import AdminUser
from app.providers.csv_io import provider as provider_module
from app.providers.csv_io.models import ImportJobRecord
from app.providers.media_local import remote
from app.providers.media_local.models import MediaAsset
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_row,
    bank_with,
    make_bank,
    make_quiz,
    open_quiz_run,
    published_quiz,
)
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


TWO_LANGUAGES = 'quiz,Kvíz,Popis,"cs,en",,,,,'


def many_warnings(uploader, questions):
    """Each question lacks its English text, so each gives a warning."""
    return upload(uploader, csv_of(TWO_LANGUAGES, *[GOOD] * questions))


def rows_in(html):
    return html.count("<tr>") - 1  # without the header row


def test_many_warnings_scroll_in_their_own_table_and_can_be_shown_all(uploader):
    """AC-158: more than 15 warnings sit in a scrollable region, and a link shows all of them."""
    many_warnings(uploader, 20)
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert 'class="issues-scroll"' in html and 'tabindex="0"' in html
    assert rows_in(html) >= 20
    assert 'href="?lang=en&amp;all=1"' in html
    full = text(uploader.get(job_url("check") + "?lang=en&all=1"))
    assert "issues-scroll" not in full
    assert rows_in(full) == rows_in(html)
    assert 'href="?lang=en"' in full


def test_few_warnings_show_without_a_region_or_a_link(uploader):
    many_warnings(uploader, 5)
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "issues-scroll" not in html and "all=1" not in html
    assert rows_in(html) >= 5


def test_the_report_scrolls_its_warnings_too(uploader):
    many_warnings(uploader, 20)
    uploader.post(job_url("confirm"))
    html = text(uploader.get(job_url("report") + "?lang=en"))
    assert 'class="issues-scroll"' in html and 'href="?lang=en&amp;all=1"' in html
    assert "issues-scroll" not in text(uploader.get(job_url("report") + "?lang=en&all=1"))


def test_the_bank_page_offers_replacing_only_with_questions(logged_in):
    full = bank_with(1)
    empty = make_bank("Prázdná")
    assert f"target=bank_replace:{full.id}" in text(logged_in.get(f"/admin/banks/{full.id}"))
    assert "bank_replace" not in text(logged_in.get(f"/admin/banks/{empty.id}"))


def test_replace_check_page_shows_the_effect_and_the_quizzes(uploader):
    bank = bank_with(2)
    add_row(make_quiz(slug="pouziva-banku"), bank)
    assert upload(uploader, csv_of(GOOD, GOOD), target=f"bank_replace:{bank.id}").status_code == 302
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "pouziva-banku" in html
    assert "Replace the questions" in html
    assert "Questions of the bank that will be deleted: 2" in html
    assert BankQuestion.objects.filter(bank=bank).count() == 2


def test_replace_check_page_without_quizzes_says_so(uploader):
    bank = bank_with(1)
    upload(uploader, csv_of(GOOD), target=f"bank_replace:{bank.id}")
    assert "No quiz draws from this bank." in text(uploader.get(job_url("check") + "?lang=en"))


def test_confirming_a_replace_swaps_the_questions_and_the_report_counts(uploader):
    """AC-165: the bank holds the file's questions, the draw row follows, the report counts."""
    bank = bank_with(2)
    quiz = make_quiz(slug="pouziva-banku")
    add_row(quiz, bank)
    imported(uploader, csv_of(GOOD, GOOD, GOOD), target=f"bank_replace:{bank.id}")
    assert BankQuestion.objects.filter(bank=bank).count() == 3
    html = text(uploader.get(job_url("report") + "?lang=en"))
    assert "Questions added: 3" in html
    assert "Questions removed: 2" in html
    assert authoring.editable_draws(quiz)[0]["bank_id"] == str(bank.id)


def test_a_file_with_an_error_row_is_refused_on_the_check_page(uploader):
    bank = bank_with(2)
    upload(uploader, csv_of(GOOD, BAD), target=f"bank_replace:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "Replacing needs every row to be usable" in html
    assert "/confirm" not in html
    uploader.post(job_url("confirm"))
    assert BankQuestion.objects.filter(bank=bank).count() == 2


def test_a_failed_save_reports_that_nothing_was_replaced(uploader):
    bank = bank_with(2)
    incomplete = "question,,,,choice,Bez možností,,,"
    imported(uploader, csv_of(GOOD, incomplete), target=f"bank_replace:{bank.id}")
    html = text(uploader.get(job_url("report") + "?lang=en"))
    assert "nothing was replaced" in html
    assert BankQuestion.objects.filter(bank=bank).count() == 2


def test_upload_again_keeps_the_replace_mode(uploader):
    bank = bank_with(1)
    upload(uploader, csv_of(GOOD), target=f"bank_replace:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert f"target=bank_replace:{bank.id}" in html


def test_a_published_revision_keeps_its_copies_after_a_replace(uploader):
    bank = bank_with(2)
    quiz = make_quiz(slug="pouziva-banku", locales=("cs",))
    add_row(quiz, bank, count=1)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    before = authoring.latest_published(quiz).snapshot_json
    imported(uploader, csv_of(GOOD, GOOD), target=f"bank_replace:{bank.id}")
    assert authoring.latest_published(quiz).snapshot_json == before
    assert authoring.banks_changed(quiz) is True


def test_replace_target_of_a_missing_bank_is_404(logged_in):
    assert logged_in.get(f"/admin/import/new?target=bank_replace:{ADMIN_ID}").status_code == 404


def test_a_broken_image_found_at_confirm_stops_the_replace(uploader):
    """AC-165: the file passes the check, the image fails at confirm, nothing is replaced."""
    bank = bank_with(2)
    head = QUIZ_HEAD + ",image,image_alt_cs"
    data = csv_of(
        f"{GOOD},good.png,Popis",
        "question,,,,choice,Vadný obrázek,A,B,A,bad.png,Popis",
        head=head,
    )
    body = zip_of({"q.csv": data, "good.png": png(), "bad.png": b"this is no image"})
    imported(uploader, body, target=f"bank_replace:{bank.id}", name="q.zip")
    html = text(uploader.get(job_url("report") + "?lang=en"))
    assert "nothing was replaced" in html
    assert BankQuestion.objects.filter(bank=bank).count() == 2


FOLDER_HEAD = QUIZ_HEAD + ",folder"


def with_folders(*paths):
    return csv_of(*(f"{GOOD},{path}" for path in paths), head=FOLDER_HEAD)


def add_bank_question_to(bank, folder):
    add_bank_question(bank, locales=("cs",), folder=folder)


def folder_of(bank, path):
    return bank_folders.ensure_path(bank, path, admin_id=ADMIN_ID)


def test_the_check_page_of_a_bank_import_shows_the_folder_tree(uploader):
    bank = make_bank()
    upload(uploader, with_folders("EU/geopolitika"), target=f"bank:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "Where the questions go" in html
    assert "geopolitika" in html
    assert "new folder" in html
    assert "Apply the structure" in html
    ImportJobRecord.objects.all().delete()
    upload(uploader, csv_of(QUIZ_ROW, GOOD))
    assert "Apply the structure" not in text(uploader.get(job_url("check") + "?lang=en"))


def test_applying_the_structure_and_confirming_uses_it(uploader):
    """AC-166: the admin removes the file's top folder and the replace fills the bank's own."""
    bank = make_bank()
    old = folder_of(bank, "geopolitika")
    add_bank_question_to(bank, old)
    quiz = make_quiz(slug="evropa")
    add_row(quiz, bank, count=2, folder_id=str(old.pk))
    upload(
        uploader, with_folders("EU/geopolitika", "EU/geopolitika"), target=f"bank_replace:{bank.id}"
    )
    html = text(uploader.get(job_url("check") + "?lang=en&drop_0=1"))
    assert "existing folder" in html
    assert 'name="drop_0"' in html
    uploader.post(job_url("confirm"), {"drop_0": "1"})
    assert BankQuestion.objects.filter(bank=bank, folder=old).count() == 2
    assert not bank.folders.filter(name="EU").exists()


def test_a_tampered_structure_imports_nothing(uploader):
    bank = bank_with(1)
    foreign = folder_of(make_bank("Cizí"), "cizí")
    upload(uploader, with_folders("EU/a"), target=f"bank:{bank.id}")
    uploader.post(job_url("confirm"), {"under": str(foreign.pk)})
    assert "no longer valid" in text(uploader.get(job_url("report") + "?lang=en"))
    assert BankQuestion.objects.filter(bank=bank).count() == 1


def test_a_bad_name_on_the_check_page_hides_the_confirm(uploader):
    bank = make_bank()
    upload(uploader, with_folders("EU/a"), target=f"bank:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en&name_0=a/b"))
    assert "no slash" in html
    assert "/confirm" not in html


def test_the_replace_check_lists_short_draw_rows(uploader):
    bank = bank_with(3)
    obchod = folder_of(bank, "obchod")
    BankQuestion.objects.filter(bank=bank).update(folder=obchod)
    add_row(make_quiz(slug="evropa"), bank, count=3, folder_id=str(obchod.pk))
    upload(uploader, with_folders("EU/obchod"), target=f"bank_replace:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "evropa · obchod · 0 of 3" in html
    html = text(uploader.get(job_url("check") + "?lang=en&drop_0=1"))
    assert "evropa · obchod · 1 of 3" in html


def test_a_refused_replace_still_shows_the_structure(uploader):
    bank = bank_with(1)
    data = csv_of(f"{GOOD},EU", f"{BAD},EU", head=FOLDER_HEAD)
    upload(uploader, data, target=f"bank_replace:{bank.id}")
    html = text(uploader.get(job_url("check") + "?lang=en"))
    assert "Replacing needs every row to be usable" in html
    assert "Apply the structure" in html


def test_a_structure_that_makes_every_row_too_deep_keeps_the_form(uploader):
    bank = make_bank()
    deep = folder_of(bank, "a/b/c")
    upload(uploader, with_folders("x/y"), target=f"bank:{bank.id}")
    html = text(uploader.get(job_url("check") + f"?lang=en&under={deep.pk}"))
    assert "deeper than 4 levels" in html
    assert "Apply the structure" in html


def test_the_name_field_of_a_top_folder_says_folder_name(uploader):
    bank = make_bank()
    upload(uploader, with_folders("EU/a"), target=f"bank:{bank.id}")
    assert "Folder name" in text(uploader.get(job_url("check") + "?lang=en"))
