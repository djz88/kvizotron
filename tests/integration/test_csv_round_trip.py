"""Export followed by import gives the same content (AC-52, ADR-0032)."""

import csv
import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import MULTIPART_CONTENT
from PIL import Image

from app.contracts import QuestionTypePlugin
from app.domain import authoring, settings
from app.domain.models import BankQuestion, Quiz
from app.domain.questions import images_of
from app.kernel import registry
from app.kernel.models import AdminUser, AuditEvent
from app.providers.csv_io.models import ImportJobRecord
from app.providers.media_local import remote
from app.providers.media_local.provider import LocalMediaStorage
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    make_bank,
    make_quiz,
)
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
LOCALES = ("cs", "en")


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)


@pytest.fixture
def client():
    client = FormClient()
    client.force_login(AdminUser.objects.create_admin("alice", "dlouhe-a-neobvykle-heslo"))
    return client


def both(text):
    return {locale: f"{text} {locale}" for locale in LOCALES}


def plugin_of(type_id):
    return registry.get("question_type", type_id)


def choice_form(prompt, **fields):
    form = {f"prompt_{lo}": [prompt[lo]] for lo in LOCALES} | fields
    for row, text in enumerate(("Ano", "Ne")):
        for lo in LOCALES:
            form[f"option_{row}_{lo}"] = [f"{text} {lo}"]
    return form


def rich_quiz():
    """Everything a file can hold."""
    quiz = make_quiz("bohaty", locales=LOCALES)
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=ADMIN_ID)
    asset = LocalMediaStorage().store_image(png())
    choice = plugin_of("choice")
    matching = plugin_of("matching")
    many = choice.parse_admin(
        choice_form(both("Víc"), correct_0=["1"], correct_1=["1"], allow_multiple=["1"]), LOCALES
    )
    authoring.save_question(
        quiz,
        None,
        "choice",
        many,
        points=3,
        sources=["Kniha", "https://example.test/x"],
        explanation=both("Proto"),
        setting_values={settings.SHOW_SOURCES: "on"},
    )
    formula = choice.parse_admin(choice_form({"cs": "=1+1", "en": "-2"}, correct_1=["1"]), LOCALES)
    authoring.save_question(quiz, None, "choice", formula)
    yes_no = choice.parse_admin(
        choice_form(both("Ano nebo ne"), correct_0=["1"], kind=["yes_no"]), LOCALES
    )
    authoring.save_question(quiz, None, "choice", yes_no)
    imaged = choice.parse_admin(
        choice_form(
            both("S obrázky"),
            correct_0=["1"],
            image_asset=[asset],
            image_alt_cs=["Popis"],
            image_alt_en=["Alt"],
            image_source=[],
            option_0_image_asset=[asset],
            option_0_image_source=["https://example.test/o.png"],
            option_0_image_alt_cs=["Volba"],
            option_0_image_alt_en=["Option"],
        ),
        LOCALES,
    )
    authoring.save_question(quiz, None, "choice", imaged)
    pairs = {f"prompt_{lo}": [f"Páry {lo}"] for lo in LOCALES} | {"mode": ["pairs"]}
    order = {f"prompt_{lo}": [f"Pořadí {lo}"] for lo in LOCALES} | {
        "mode": ["order"],
        "direction": ["bottom_up"],
    }
    for row in range(2):
        for lo in LOCALES:
            pairs[f"item_{row}_{lo}"] = [f"L{row} {lo}"]
            pairs[f"match_{row}_{lo}"] = [f"P{row} {lo}"]
            order[f"item_{row}_{lo}"] = [f"K{row} {lo}"]
    authoring.save_question(quiz, None, "matching", matching.parse_admin(pairs, LOCALES))
    authoring.save_question(quiz, None, "matching", matching.parse_admin(order, LOCALES))
    return quiz


def question_content(question, locales):
    plugin: QuestionTypePlugin = plugin_of(question["type"])
    return {
        "type": question["type"],
        "definition": [
            (row.label, row.locale, row.value)
            for row in plugin.describe_definition(question["definition"], locales)
            if "image" not in row.key
        ],
        "images": sorted(
            (bool(image.get("asset")), image.get("source") or "", sorted(image["alt"].items()))
            for image in images_of(question["definition"])
        ),
        "scoring": question["scoring"],
        "settings": question["settings"],
        "sources": question["sources"],
        "explanation": question["explanation"],
    }


def content_of(quiz):
    return {
        "title": quiz.title,
        "description": quiz.description,
        "locales": quiz.supported_locales,
        "default": quiz.default_locale,
        "navigation": settings.quiz_override(settings.NAVIGATION_MODE, quiz),
        "reveal": settings.quiz_override(settings.REVEAL_MOMENT, quiz),
        "questions": [
            question_content(question, quiz.supported_locales)
            for question in authoring.editable_questions(quiz)
        ],
    }


def export(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return response


def reimport(client, response, target="new_quiz"):
    disposition = response["Content-Disposition"]
    name = "export.zip" if ".zip" in disposition else "export.csv"
    file = SimpleUploadedFile(name, response.content)
    client.post(
        f"/admin/import/new?target={target}", {"file": file}, content_type=MULTIPART_CONTENT
    )
    job = ImportJobRecord.objects.order_by("-created_at").first()
    page = client.get(f"/admin/import/{job.pk}/check?lang=en")
    client.post(f"/admin/import/{job.pk}/confirm")
    return job, page


def test_round_trip_keeps_the_content_of_both_types_images_settings_and_formula_text(
    client, monkeypatch
):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png())
    quiz = rich_quiz()
    response = export(client, f"/admin/quizzes/{quiz.id}/export")
    assert response["Content-Type"] == "application/zip"
    assert "bohaty" in response["Content-Disposition"]
    reimport(client, response)
    imported = Quiz.objects.exclude(pk=quiz.pk).get()
    assert imported.slug == "bohaty-2"
    assert content_of(imported) == content_of(quiz)


def test_bank_round_trip_keeps_tags(client):
    bank = make_bank()
    add_bank_question(bank, locales=LOCALES, tags=("eu", "dějepis"), prompt="První")
    response = export(client, f"/admin/banks/{bank.id}/export")
    assert "text/csv" in response["Content-Type"]
    other = make_bank("Druhá")
    reimport(client, response, target=f"bank:{other.id}")
    source = BankQuestion.objects.get(bank=bank)
    copy = BankQuestion.objects.get(bank=other)
    assert sorted(copy.tags) == sorted(source.tags)
    filled = {k: v for k, v in copy.question_json["definition"]["prompt"].items() if v}
    assert filled == source.question_json["definition"]["prompt"]


def test_local_image_gives_zip_and_address_image_gives_only_the_address(client):
    quiz = rich_quiz()
    response = export(client, f"/admin/quizzes/{quiz.id}/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
    assert "questions.csv" in names
    assert len([name for name in names if name.startswith("images/")]) == 1


def test_no_local_image_gives_csv(client):
    quiz = make_quiz(locales=LOCALES)
    add_question(quiz)
    response = export(client, f"/admin/quizzes/{quiz.id}/export")
    assert "text/csv" in response["Content-Type"]
    assert ".csv" in response["Content-Disposition"]


def test_exported_cell_never_starts_with_a_formula_character(client):
    quiz = rich_quiz()
    response = export(client, f"/admin/quizzes/{quiz.id}/export")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        data = archive.read("questions.csv").decode("utf-8-sig")
    for row in csv.reader(io.StringIO(data, newline="")):
        for cell in row:
            assert not cell or cell[0] not in "=+-@\t\r"


def test_quiz_with_draw_rows_says_on_page_they_are_left_out(client):
    quiz = make_quiz(locales=LOCALES)
    assert (
        "are not included"
        not in client.get(f"/admin/quizzes/{quiz.id}/edit?lang=en").content.decode()
    )
    add_row(quiz, bank_with(2, locales=LOCALES))
    assert (
        "are not included" in client.get(f"/admin/quizzes/{quiz.id}/edit?lang=en").content.decode()
    )


def test_export_is_audited_and_requires_login(client):
    quiz = make_quiz(locales=LOCALES)
    bank = make_bank()
    anonymous = FormClient()
    assert anonymous.get(f"/admin/quizzes/{quiz.id}/export").status_code == 302
    assert anonymous.get(f"/admin/banks/{bank.id}/export").status_code == 302
    export(client, f"/admin/quizzes/{quiz.id}/export")
    export(client, f"/admin/banks/{bank.id}/export")
    assert AuditEvent.objects.filter(action="export.downloaded").count() == 2


def test_imported_export_has_no_unused_columns_and_no_errors(client, monkeypatch):
    monkeypatch.setattr(remote, "fetch", lambda *a, **k: png())
    quiz = rich_quiz()
    job, page = reimport(client, export(client, f"/admin/quizzes/{quiz.id}/export"))
    html = page.content.decode()
    assert "Columns not used" not in html
    assert "Rows that will be skipped" not in html
    assert "/mapping" not in html


def test_download_buttons(client):
    quiz = make_quiz(locales=LOCALES)
    bank = make_bank()
    assert (
        f"/admin/quizzes/{quiz.id}/export"
        in client.get(f"/admin/quizzes/{quiz.id}/edit").content.decode()
    )
    assert (
        f"/admin/banks/{bank.id}/export" in client.get(f"/admin/banks/{bank.id}").content.decode()
    )
