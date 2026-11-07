from decimal import Decimal

import pytest
from django.utils import translation

from app.contracts import AdminFormError, CsvRowError, ItemGrade
from app.plugins.questions.number.plugin import NumberQuestion, parse_number
from tests.contracts.question_type import HOSTILE, QuestionTypeContract

PLUGIN = NumberQuestion()


def config_of(value="1000", tolerance="5", kind="percent", **fields):
    return {
        "prompt": {"cs": "Kolik?", "uk": "Скільки?"},
        "value": value,
        "tolerance": tolerance,
        "tolerance_kind": kind,
        **fields,
    }


def form(**fields):
    base = {
        "prompt_cs": ["Kolik?"],
        "value": ["1000"],
        "tolerance": ["5"],
        "tolerance_kind": ["percent"],
    }
    return base | {key: [value] for key, value in fields.items()}


class TestNumber(QuestionTypeContract):
    plugin = PLUGIN
    definition = config_of()
    answer_key_values = ["1000", '"tolerance"']
    valid_answer = {"value": "997"}
    correct_answer = {"value": "1000"}
    malformed_answers = [{"value": "abc"}, {"value": "1e5"}, {"value": 3}, "x", None]
    admin_form = form()
    changed_definitions = [
        config_of(value="2000"),
        config_of(tolerance="7"),
        config_of(kind="absolute"),
        config_of() | {"prompt": {"cs": "Jinak?", "uk": "Скільки?"}},
        config_of(image={"asset": "a" * 32, "alt": {"cs": "Popis"}}),
    ]
    answer_marker = 'value="997"'
    hostile_definition = {
        "prompt": {"cs": HOSTILE},
        "value": HOSTILE,
        "tolerance": HOSTILE,
        "tolerance_kind": "absolute",
    }
    solution_marker = "1000"
    csv_bad_cells = [
        {"prompt_cs": "", "correct_value": "1"},
        {"prompt_cs": "Q", "correct_value": ""},
        {"prompt_cs": "Q", "correct_value": "abc"},
        {"prompt_cs": "Q", "correct_value": "0", "tolerance": "5", "tolerance_kind": "percent"},
        {"prompt_cs": "Q", "correct_value": "1", "tolerance": "x", "tolerance_kind": "absolute"},
        {"prompt_cs": "Q", "correct_value": "1", "tolerance": "1", "tolerance_kind": "weird"},
    ]


def right(config, text):
    return PLUGIN.grade(config, {"value": text}) == ItemGrade(1, 0, 1)


@pytest.mark.parametrize(
    "text,value", [("3,14", "3.14"), ("3.14", "3.14"), ("-2", "-2"), (" 7 ", "7")]
)
def test_reads_comma_and_dot(text, value):
    assert parse_number(text) == Decimal(value)


@pytest.mark.parametrize(
    "text",
    ["1,000.5", "1.2.3", "1e5", "NaN", "Infinity", "", "١٢", "1 000", "--1", "1" * 31, ",5", "5,"],
)
def test_refuses(text):
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize(
    "answer,expected",
    [("950", True), ("1050", True), ("949.99", False), ("1050,01", False), ("1000,0", True)],
)
def test_percent_tolerance_is_inclusive(answer, expected):
    assert right(config_of(), answer) is expected


def test_percent_uses_the_absolute_value():
    config = config_of(value="-100", tolerance="10")
    assert right(config, "-110") and right(config, "-90")
    assert not right(config, "-111") and not right(config, "-89")


def test_absolute_tolerance():
    config = config_of(value="10", tolerance="0,5", kind="absolute")
    assert right(config, "9.5") and right(config, "10.5")
    assert not right(config, "10.51")


def test_no_tolerance_is_exact():
    config = config_of(value="3.14", tolerance="", kind="none")
    assert right(config, "3,140") and not right(config, "3.141")


def test_exact_decimals_not_floats():
    assert right(config_of(value="0.1", tolerance="0.2", kind="absolute"), "0.3")


def test_no_answer_scores_nothing_and_is_not_wrong():
    assert PLUGIN.grade(config_of(), {}) == ItemGrade(0, 0, 1)
    assert PLUGIN.grade(config_of(), {"value": ""}) == ItemGrade(0, 0, 1)
    PLUGIN.validate_submission(config_of(), {"value": " "})


def test_percent_on_zero_is_refused_by_the_editor():
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(form(value="0"), ["cs"])
    assert error.value.config["value"] == "0"


@pytest.mark.parametrize(
    "fields", [{"value": "abc"}, {"tolerance": "x"}, {"tolerance": "-1"}, {"tolerance": "1e2"}]
)
def test_the_editor_refuses_what_it_cannot_read(fields):
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(**fields), ["cs"])


def test_the_editor_stores_a_dot_and_keeps_an_unset_value_for_later():
    config = PLUGIN.parse_admin(form(value="3,14", tolerance="0,5"), ["cs"])
    assert config["value"] == "3.14" and config["tolerance"] == "0.5"
    empty = PLUGIN.parse_admin(form(value=""), ["cs"])
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(empty, "cs")


def test_no_tolerance_drops_the_value():
    config = PLUGIN.parse_admin(form(tolerance="", tolerance_kind="none"), ["cs"])
    assert config["tolerance"] == "" and config["tolerance_kind"] == "none"


def test_public_payload_holds_no_value_or_tolerance():
    payload = PLUGIN.public_payload(config_of(), "cs")
    assert set(payload) == {"prompt"}


def test_input_allows_only_number_characters():
    html = PLUGIN.render_public({"id": "q1", "prompt": "Kolik?"}, "cs")
    assert 'name="q1:value"' in html
    assert 'pattern="-?[0-9]+([.,][0-9]+)?"' in html
    assert 'type="text"' in html and "<label" in html


def test_solution_shows_value_and_tolerance():
    with translation.override("cs"):
        html = PLUGIN.render_solution(config_of(value="3.5"), "cs", {"value": "9"})
    assert "3,5" in html and "5 %" in html and "9" in html
    with translation.override("en"):
        html = PLUGIN.render_solution(config_of(value="3.5", kind="absolute"), "en", None)
    assert "3.5" in html and "±" in html


def test_csv_reads_comma_values():
    config = PLUGIN.from_csv({"prompt_cs": "Q", "correct_value": "3,5"}, ["cs"])
    assert config["value"] == "3.5" and config["tolerance_kind"] == "none"


def test_csv_refuses_for_the_right_column():
    with pytest.raises(CsvRowError) as error:
        PLUGIN.from_csv({"prompt_cs": "Q", "correct_value": "abc"}, ["cs"])
    assert error.value.column == "correct_value"
