"""The sample and the column description are what people and LLMs learn the format from."""

from pathlib import Path

import pytest

from app.contracts import ParsedFile
from app.domain import question_import
from app.domain.question_import import Target
from app.kernel import registry
from app.providers.csv_io import provider
from app.providers.csv_io.reader import parse_csv

pytestmark = pytest.mark.django_db
SAMPLE = Path(provider.__file__).parent / "sample"


def plan():
    columns, rows = parse_csv((SAMPLE / "quiz-sample.csv").read_bytes())
    return question_import.interpret(
        ParsedFile(columns, rows, frozenset()), Target("new_quiz", None, None), {}, None
    )


def test_sample_holds_five_questions_in_three_languages_with_explanations_and_sources():
    planned = plan()
    assert planned.quiz.locales == ["cs", "en", "uk"]
    assert len(planned.questions) == 5
    for question in planned.questions:
        assert set(question.explanation) == {"cs", "en", "uk"}
        assert question.sources
        assert len(question.config["options"]) == 5
    several = [q for q in planned.questions if len(q.config["correct"]) > 1]
    assert several


def test_sample_has_no_errors_no_warnings_and_needs_no_mapping():
    planned = plan()
    assert planned.issues == []
    assert planned.unused_columns == []
    columns, _rows = parse_csv((SAMPLE / "quiz-sample.csv").read_bytes())
    assert question_import.unknown_columns(columns) == []


def test_format_description_names_every_column_of_every_type_and_common_column():
    text = (SAMPLE / "csv-format.md").read_text()
    names = list(question_import.PLAIN_COLUMNS)
    names += [f"{name}_<language>" for name in question_import.PER_LANGUAGE]
    names.append("setting_<key>")
    names += ["prompt_<language>", "kind", "allow_multiple", "reveal_count", "correct", "image"]
    names += ["image_alt_<language>", "option_<N>_<language>", "option_<N>_image"]
    names += ["option_<N>_image_alt_<language>", "config_json"]
    names += ["correct_value", "tolerance", "tolerance_kind"]
    names += ["answer_<N>_<language>", "ignore_case", "ignore_spaces", "ignore_diacritics"]
    names += ["auto_points", "auto_share"]
    for name in names:
        assert f"`{name}`" in text, name
    assert set(registry.keys("question_type")) == {
        "choice",
        "image_answer",
        "matching",
        "number",
        "text",
    }
