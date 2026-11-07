"""What a download holds."""

import pytest

from app.domain import authoring, question_export, settings
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    definition,
    make_bank,
    make_quiz,
    published_quiz,
)

pytestmark = pytest.mark.django_db


def question_rows(data):
    return [row for row in data.rows if row.get("row_type") != "quiz"]


def test_quiz_row_comes_first_with_fields_and_overrides():
    quiz = make_quiz(locales=("cs", "en"))
    add_question(quiz)
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=ADMIN_ID)
    data = question_export.rows_for_quiz(quiz)
    first = data.rows[0]
    assert first["row_type"] == "quiz"
    assert first["slug"] == quiz.slug
    assert first["locales"] == "cs,en"
    assert first["default_locale"] == "cs"
    assert first["title_en"] == "Název en"
    assert first["setting_navigation_mode"] == "step_back"
    assert first["schema_version"] == "1"


def test_common_columns_come_first_in_a_fixed_order():
    quiz = make_quiz()
    add_question(quiz)
    columns = question_export.rows_for_quiz(quiz).columns
    assert columns[:2] == ["schema_version", "row_type"]
    assert columns == list(dict.fromkeys(columns))


def test_every_cell_is_a_column():
    quiz = make_quiz()
    add_question(quiz)
    data = question_export.rows_for_quiz(quiz)
    for row in data.rows:
        assert set(row) <= set(data.columns)


def test_draft_preferred_then_published():
    quiz = published_quiz()
    assert len(question_rows(question_export.rows_for_quiz(quiz))) == 1
    add_question(quiz, prompt="V konceptu")
    rows = question_rows(question_export.rows_for_quiz(quiz))
    assert len(rows) == 2
    assert rows[1]["prompt_cs"] == "V konceptu cs"


def test_question_fields():
    quiz = make_quiz()
    question = add_question(quiz)
    authoring.save_question(
        quiz,
        question,
        "choice",
        definition(("cs",)),
        points=4,
        sources=["a", "b"],
        explanation={"cs": "Proto"},
        setting_values={settings.SHOW_SOURCES: "on"},
    )
    row = question_rows(question_export.rows_for_quiz(quiz))[0]
    assert row["type"] == "choice"
    assert row["points"] == "4"
    assert row["sources"] == "a\nb"
    assert row["explanation_cs"] == "Proto"
    assert row["setting_show_sources"] == "on"
    assert row["correct"] == "A"
    assert row["scoring"]


def test_draw_rows_are_left_out_and_said_so():
    quiz = make_quiz()
    add_question(quiz)
    assert question_export.rows_for_quiz(quiz).omitted_draws is False
    add_row(quiz, bank_with(2))
    data = question_export.rows_for_quiz(quiz)
    assert data.omitted_draws is True
    assert len(question_rows(data)) == 1


def test_uploaded_image_gets_a_file_name_and_address_image_keeps_its_address():
    quiz = make_quiz()
    config = definition(("cs",)) | {
        "image": {"asset": "aaaa", "alt": {"cs": "Popis"}},
    }
    config["options"][0]["image"] = {
        "asset": "bbbb",
        "source": "https://example.test/o.png",
        "alt": {"cs": "x"},
    }
    authoring.save_question(quiz, None, "choice", config)
    data = question_export.rows_for_quiz(quiz)
    row = question_rows(data)[0]
    assert row["image"] == "images/aaaa"
    assert row["option_1_image"] == "https://example.test/o.png"
    assert data.assets == {"images/aaaa": "aaaa"}


def test_export_does_not_change_the_stored_definition():
    quiz = make_quiz()
    config = definition(("cs",)) | {"image": {"asset": "aaaa", "alt": {"cs": "Popis"}}}
    authoring.save_question(quiz, None, "choice", config)
    question_export.rows_for_quiz(quiz)
    assert "source" not in authoring.editable_questions(quiz)[0]["definition"]["image"]


def test_bank_has_no_quiz_row_and_no_points_and_keeps_tags():
    bank = make_bank()
    add_bank_question(bank, tags=("EU", "Dějepis"))
    data = question_export.rows_for_bank(bank)
    assert len(data.rows) == 1
    row = data.rows[0]
    assert row["row_type"] == "question"
    assert "points" not in row
    assert len(row["tags"].split(",")) == 2
