from decimal import Decimal

import pytest

from app.contracts import AdminFormError, ItemGrade
from app.domain.models import AttemptAnswer  # noqa: F401  # the app registry is ready
from app.kernel import registry
from app.plugins.questions.image_answer.plugin import ImageAnswerQuestion
from tests.contracts.question_type import HOSTILE, QuestionTypeContract

PLUGIN = ImageAnswerQuestion()
ASSET = "a" * 32


def config_of(right=100, total=100, **fields):
    return {
        "prompt": {"cs": "Vyfoťte pomník", "uk": "Сфотографуйте пам'ятник"},
        "auto": {"right": right, "total": total},
        **fields,
    }


def form(**fields):
    base = {"prompt_cs": ["Vyfoťte"], "points": ["10"], "auto_points": ["2"]}
    return base | {key: [value] for key, value in fields.items()}


class TestImageAnswer(QuestionTypeContract):
    plugin = PLUGIN
    definition = config_of()
    answer_key_values = ['"auto"', '"right"']
    valid_answer = {"image": ASSET}
    correct_answer = {"image": ASSET}
    malformed_answers = [{"image": 3}, {"image": "../etc"}, {"image": ["x"]}, "x", None]
    admin_form = form()
    changed_definitions = [
        config_of(right=5),
        config_of(total=200),
        config_of() | {"prompt": {"cs": "Jinak", "uk": "Сфотографуйте пам'ятник"}},
        config_of(image={"asset": "b" * 32, "alt": {"cs": "Popis"}}),
    ]
    answer_marker = "data-photo-sent"
    hostile_definition = {"prompt": {"cs": HOSTILE}, "auto": {"right": 0, "total": 1}}
    solution_marker = "solution"
    csv_bad_cells = [
        {"prompt_cs": "", "auto_points": "1"},
        {"prompt_cs": "Q", "auto_points": "x"},
        {"prompt_cs": "Q", "auto_share": "101"},
        {"prompt_cs": "Q", "auto_share": "a"},
        {"prompt_cs": "Q", "auto_points": "9", "points": "5"},
        {"prompt_cs": "Q", "auto_points": "2"},
    ]


def test_two_of_ten_pays_two_through_partial():
    grade = PLUGIN.grade(config_of(2, 10), {"image": ASSET})
    assert grade == ItemGrade(2, 0, 10)
    strategy = registry.get("scoring_strategy", "partial", include_disabled=True)
    assert strategy.evaluate(grade, {"points": 10}).earned_points == 2
    assert PLUGIN.available_scoring_strategies() == ["partial"]


def test_without_an_image_nothing_is_paid():
    assert PLUGIN.grade(config_of(2, 10), {}).right == 0
    assert PLUGIN.needs_grading(config_of(2, 10), {}) is False
    assert PLUGIN.needs_grading(config_of(2, 10), {"image": ASSET}) is True


def test_a_full_quiz_form_stores_the_points():
    assert PLUGIN.parse_admin(form(), ["cs"])["auto"] == {"right": 2, "total": 10}


def test_automatic_above_total_refused():
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(auto_points="11"), ["cs"])


@pytest.mark.parametrize("value", ["1.5", "x", "-1"])
def test_automatic_points_are_whole(value):
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(auto_points=value), ["cs"])


def test_zero_automatic_is_allowed():
    config = PLUGIN.parse_admin(form(auto_points="0"), ["cs"])
    assert config["auto"] == {"right": 0, "total": 10}
    PLUGIN.validate_definition(config, "cs")
    assert PLUGIN.parse_admin(form(auto_points=""), ["cs"])["auto"]["right"] == 0


def test_without_points_the_form_reads_a_percent():
    config = PLUGIN.parse_admin({"prompt_cs": ["Q"], "auto_percent": ["20"]}, ["cs"])
    assert config["auto"] == {"right": 20, "total": 100}
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin({"prompt_cs": ["Q"], "auto_percent": ["101"]}, ["cs"])


@pytest.mark.parametrize(
    "percent,points,earned",
    [(20, 5, "1"), (33, 5, "1.65"), (0, 5, "0")],
)
def test_row_of_points_at_a_percent(percent, points, earned):
    grade = PLUGIN.grade(config_of(percent, 100), {"image": ASSET})
    strategy = registry.get("scoring_strategy", "partial", include_disabled=True)
    assert strategy.evaluate(grade, {"points": points}).earned_points == Decimal(earned)


def test_public_page_has_a_keyboard_file_field_with_a_label():
    html = PLUGIN.render_public({"id": "q1", "prompt": "Vyfoťte"}, "cs")
    assert 'type="file"' in html and 'name="q1:image"' in html and "<label" in html
    assert 'accept="image/png,image/jpeg,image/webp"' in html


def test_public_level_warns_before_upload_only_when_set():
    public = PLUGIN.public_payload(config_of(), "cs", {"photo_visibility": "public"})
    assert public["may_be_public"] is True
    html = PLUGIN.render_public({**public, "id": "q1"}, "cs")
    assert 'role="note"' in html
    private = PLUGIN.public_payload(config_of(), "cs", {"photo_visibility": "author"})
    assert not private["may_be_public"]
    assert 'role="note"' not in PLUGIN.render_public({**private, "id": "q1"}, "cs")


def test_file_field_is_declared():
    assert PLUGIN.file_fields(config_of()) == ["image"]
    assert PLUGIN.question_settings() == ["photo_visibility"]


def test_public_payload_tells_nothing_about_the_split():
    assert set(PLUGIN.public_payload(config_of(), "cs")) == {"prompt", "may_be_public"}


def test_csv_round_trip_keeps_the_split():
    cells = PLUGIN.to_csv(config_of(2, 10), ["cs"])
    assert cells["auto_points"] == "2" and cells["auto_share"] == ""
    assert PLUGIN.from_csv(cells | {"points": "10"}, ["cs"])["auto"] == {"right": 2, "total": 10}
    cells = PLUGIN.to_csv(config_of(33, 100), ["cs"])
    assert cells["auto_share"] == "33" and cells["auto_points"] == ""
    assert PLUGIN.from_csv(cells, ["cs"])["auto"] == {"right": 33, "total": 100}
