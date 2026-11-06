import pytest
from django.utils import translation

from app.plugins.questions.choice_single.plugin import ChoiceSingleQuestion
from tests.contracts.question_type import QuestionTypeContract

PLUGIN = ChoiceSingleQuestion()


def definition(correct="aaaa1111", prompt_uk="Питання", option_uk="Так"):
    return {
        "prompt": {"cs": "Otázka", "uk": prompt_uk},
        "options": [
            {"id": "aaaa1111", "text": {"cs": "Ano", "uk": option_uk}},
            {"id": "bbbb2222", "text": {"cs": "Ne", "uk": "Ні"}},
        ],
        "correct": correct,
    }


class TestChoiceSingle(QuestionTypeContract):
    plugin = PLUGIN
    definition = definition()
    answer_key_values = ['"correct"']
    valid_answer = {"option": "bbbb2222"}
    malformed_answers = [{}, {"option": 3}, {"option": None}, {"option": "nope"}, "aaaa1111", None]
    admin_form = {
        "prompt_cs": ["Otázka"],
        "option_0_cs": ["Ano"],
        "option_1_cs": ["Ne"],
        "correct": ["1"],
    }


def public(correct="aaaa1111", locale="cs"):
    return PLUGIN.public_payload(definition(correct), locale)


def test_public_payload_does_not_depend_on_correct_option():
    assert public("aaaa1111") == public("bbbb2222")


def test_public_payload_is_in_the_requested_language():
    assert public(locale="uk")["prompt"] == "Питання"
    assert public(locale="uk")["options"][1] == {"id": "bbbb2222", "text": "Ні"}


def test_render_public_does_not_depend_on_correct_option():
    first = PLUGIN.render_public(public("aaaa1111"), "cs")
    assert first == PLUGIN.render_public(public("bbbb2222"), "cs")


def test_render_public_escapes_markup():
    html = PLUGIN.render_public(
        {"id": "q1", "prompt": "<script>x", "options": [{"id": "a", "text": "<b>y"}]}, "cs"
    )
    assert "<script>x" not in html and "&lt;script&gt;x" in html
    assert "<b>y" not in html


def test_render_admin_escapes_markup():
    config = definition()
    config["prompt"]["cs"] = '"><script>x'
    html = PLUGIN.render_admin(config, ["cs"])
    assert "<script>x" not in html


def test_public_inputs_are_named_by_question_id():
    html = PLUGIN.render_public({**public(), "id": "q1"}, "cs")
    assert 'name="q1:option"' in html
    assert 'value="bbbb2222"' in html


def test_rejects_answer_with_unknown_option():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(definition(), {"option": "cccc3333"})


@pytest.mark.parametrize(
    "config",
    [definition(prompt_uk=" "), definition(option_uk="")],
    ids=["prompt", "option"],
)
def test_definition_incomplete_in_locale_is_refused(config):
    PLUGIN.validate_definition(config, "cs")
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "uk")


def test_definition_with_fewer_than_two_options_is_refused():
    config = definition()
    config["options"] = config["options"][:1]
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")


def test_definition_whose_correct_option_is_missing_is_refused():
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(definition(correct="cccc3333"), "cs")


def test_parse_keeps_existing_option_ids_and_drops_blank_rows():
    config = PLUGIN.parse_admin(
        {
            "prompt_cs": ["Otázka"],
            "option_0_id": ["aaaa1111"],
            "option_0_cs": [" Ano "],
            "option_1_cs": [""],
            "option_2_id": ["bbbb2222"],
            "option_2_cs": ["Ne"],
            "correct": ["2"],
        },
        ["cs"],
    )
    assert [o["id"] for o in config["options"]] == ["aaaa1111", "bbbb2222"]
    assert config["options"][0]["text"] == {"cs": "Ano"}
    assert config["correct"] == "bbbb2222"


def test_parse_generates_random_ids_for_new_rows():
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": ["B"], "correct": ["0"]}
    first = PLUGIN.parse_admin(form, ["cs"])["options"]
    second = PLUGIN.parse_admin(form, ["cs"])["options"]
    assert first[0]["id"] != first[1]["id"]
    assert first[0]["id"] != second[0]["id"]
    assert len(first[0]["id"]) == 8


@pytest.mark.parametrize("correct", [["1"], ["x"], ["99"], []])
def test_parse_refuses_correct_not_pointing_at_a_filled_row(correct):
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": [""], "correct": correct}
    with pytest.raises(ValueError) as error:
        PLUGIN.parse_admin(form, ["cs"])
    assert error.value.config["prompt"] == {"cs": "Q"}


def test_admin_form_shows_saved_values():
    html = PLUGIN.render_admin(definition(correct="bbbb2222"), ["cs", "uk"])
    assert 'value="Otázka"' in html and 'value="Питання"' in html
    assert 'name="option_5_cs"' in html
    assert 'value="1" checked' in html


def test_plugin_label_follows_active_language():
    with translation.override("en"):
        english = PLUGIN.render_admin(definition(), ["cs"])
    with translation.override("cs"):
        czech = PLUGIN.render_admin(definition(), ["cs"])
    assert "Options" in english and "Možnosti" in czech
