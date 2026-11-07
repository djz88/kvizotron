from functools import partial

import pytest
from django.utils import translation

from app.contracts import AdminFormError, ItemGrade
from app.plugins.questions.text.plugin import MAX_BLANKS, TextQuestion, normalized
from tests.contracts.question_type import HOSTILE, QuestionTypeContract

PLUGIN = TextQuestion()
B1, B2 = "aa11aa11", "bb22bb22"


def one_field(**fields):
    return {
        "prompt": {"cs": "Hlavní město?", "uk": "Столиця?"},
        "blanks": [{"id": B1, "accepted": {"cs": ["Plzeň", "Pilsen"], "uk": ["Пльзень"]}}],
        "ignore_case": True,
        "ignore_spaces": True,
        "ignore_diacritics": False,
        **fields,
    }


def two_blanks(**fields):
    return {
        "prompt": {"cs": "{1} a {2}", "en": "{2} and {1}"},
        "blanks": [
            {"id": B1, "accepted": {"cs": ["jedna"], "en": ["one"]}},
            {"id": B2, "accepted": {"cs": ["dva"], "en": ["two"]}},
        ],
        "ignore_case": True,
        "ignore_spaces": True,
        "ignore_diacritics": False,
        **fields,
    }


def form(**fields):
    base = {
        "prompt_cs": ["Město?"],
        "accepted_1_cs": ["Praha\nPrague"],
        "ignore_case": ["on"],
        "ignore_spaces": ["on"],
    }
    return base | {key: [value] for key, value in fields.items()}


def changed_accepted():
    config = one_field()
    config["blanks"][0]["accepted"]["cs"] = ["Brno"]
    return config


class TestText(QuestionTypeContract):
    plugin = PLUGIN
    definition = one_field()
    answer_key_values = ["Plzeň", "Pilsen", '"accepted"']
    valid_answer = {"blank_1": "Brno"}
    correct_answer = {"blank_1": "plzeň"}
    malformed_answers = [{"blank_1": 3}, {"blank_1": ["x"]}, {"blank_9": "x"}, "x", None]
    admin_form = form()
    changed_definitions = [
        changed_accepted(),
        one_field(ignore_case=False),
        one_field(ignore_spaces=False),
        one_field(ignore_diacritics=True),
        one_field(prompt={"cs": "Jinak?", "uk": "Столиця?"}),
        one_field(image={"asset": "a" * 32, "alt": {"cs": "Popis"}}),
    ]
    answer_marker = 'value="Brno"'
    hostile_definition = {
        "prompt": {"cs": HOSTILE},
        "blanks": [{"id": B1, "accepted": {"cs": [HOSTILE]}}],
        "ignore_case": True,
        "ignore_spaces": True,
        "ignore_diacritics": False,
    }
    solution_marker = "Plzeň"
    csv_bad_cells = [
        {"prompt_cs": "", "answer_1_cs": "x"},
        {"prompt_cs": "Otázka"},
        {"prompt_cs": "{1} a {2}", "answer_1_cs": "x"},
        {"prompt_cs": "Q", "answer_1_cs": "x", "ignore_case": "maybe"},
    ]


def public(config, locale="cs", answer=None):
    payload = PLUGIN.public_payload(config, locale)
    return PLUGIN.render_public({**payload, "id": "q1"}, locale, answer)


def test_defaults_ignore_case_and_spaces_not_diacritics():
    assert PLUGIN.grade(one_field(), {"blank_1": "  PLZEŇ  "}) == ItemGrade(1, 0, 1)
    assert PLUGIN.grade(one_field(), {"blank_1": "Plzen"}) == ItemGrade(0, 0, 1)


def test_ignoring_diacritics_changes_only_latin():
    n = partial(normalized, ignore_case=False, ignore_spaces=False, ignore_diacritics=True)
    assert n("Plzeň") == n("Plzen")
    assert n("и") != n("й")
    assert n("ї") != n("і")


def test_ignoring_diacritics_in_a_question():
    assert PLUGIN.grade(one_field(ignore_diacritics=True), {"blank_1": "Plzen"}).right == 1


def test_case_is_respected_when_asked():
    assert PLUGIN.grade(one_field(ignore_case=False), {"blank_1": "plzeň"}).right == 0


def test_spaces_inside_collapse_only_when_asked():
    n = partial(normalized, ignore_case=False, ignore_diacritics=False)
    assert n("a   b ", ignore_spaces=True) == "a b"
    assert n("a   b ", ignore_spaces=False) == "a   b "


def test_nfc_and_nfd_compare_equal():
    n = partial(normalized, ignore_case=False, ignore_spaces=False, ignore_diacritics=False)
    assert n("Plzeň") == n("Plzeň")


def test_accepted_answers_of_any_language_count():
    assert PLUGIN.grade(one_field(), {"blank_1": "Пльзень"}).right == 1


def test_blanks_score_separately_with_partial():
    grade = PLUGIN.grade(two_blanks(), {"blank_1": "one", "blank_2": "nope"})
    assert grade == ItemGrade(1, 0, 2)
    assert PLUGIN.available_scoring_strategies() == ["all_or_nothing", "partial"]


def test_markers_in_any_order_per_language():
    cs = public(two_blanks(), "cs")
    en = public(two_blanks(), "en")
    assert cs.index("q1:blank_1") < cs.index("q1:blank_2")
    assert en.index("q1:blank_2") < en.index("q1:blank_1")


def test_no_marker_means_one_field_under_the_prompt():
    html = public(one_field())
    assert html.count("<input") == 1 and 'name="q1:blank_1"' in html
    assert html.index("Hlavní město?") < html.index("<input")


def test_marker_missing_in_one_language_fails_validation():
    config = two_blanks(prompt={"cs": "{1} a {2}", "en": "{1} only"})
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "en")


def test_a_language_without_text_is_only_reported_for_that_language():
    config = two_blanks(prompt={"cs": "{1} a {2}", "en": ""})
    PLUGIN.validate_definition(config, "cs")
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "en")


def test_marker_without_answers_fails_validation():
    config = two_blanks()
    config["blanks"][1]["accepted"] = {"cs": [], "en": []}
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")


def test_blank_needs_an_answer_in_the_language():
    config = one_field()
    config["blanks"][0]["accepted"]["uk"] = []
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "uk")


def test_more_than_ten_blanks_refused():
    markers = " ".join(f"{{{number}}}" for number in range(1, MAX_BLANKS + 2))
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(prompt_cs=markers), ["cs"])


def test_markers_with_a_gap_are_refused():
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(prompt_cs="{1} a {3}"), ["cs"])


def test_double_brace_is_a_literal_brace():
    html = public(one_field(prompt={"cs": "Množina {{1}} je {1}"}))
    assert "Množina {1} je" in html.replace("}}", "}") and html.count("<input") == 1


def test_html_around_a_marker_is_escaped():
    html = public(one_field(prompt={"cs": "<b>{1}</b>"}))
    assert "&lt;b&gt;" in html and "<b>" not in html and html.count("<input") == 1


def test_each_input_has_a_label_naming_its_blank():
    with translation.override("en"):
        html = public(two_blanks(), "cs")
    assert 'aria-label="Blank 1"' in html and 'aria-label="Blank 2"' in html


def test_accepted_answers_never_in_the_public_payload():
    import json

    payload = json.dumps(PLUGIN.public_payload(two_blanks(), "cs"), ensure_ascii=False)
    assert "jedna" not in payload and "dva" not in payload


def test_solution_lists_accepted_answers_of_the_locale():
    html = PLUGIN.render_solution(one_field(), "cs", {"blank_1": "Brno"})
    assert "Plzeň" in html and "Pilsen" in html and "Пльзень" not in html and "Brno" in html


def test_form_keeps_blank_ids_between_saves():
    config = PLUGIN.parse_admin(form(blank_1_id=B1), ["cs"])
    assert config["blanks"][0]["id"] == B1


def test_form_keeps_extra_rows_and_lines():
    config = PLUGIN.parse_admin(form(prompt_cs="{1} a {2}", accepted_2_cs="x\n\n y "), ["cs"])
    assert len(config["blanks"]) == 2
    assert config["blanks"][0]["accepted"]["cs"] == ["Praha", "Prague"]
    assert config["blanks"][1]["accepted"]["cs"] == ["x", "y"]


def test_switches_can_be_turned_off_in_the_form():
    config = PLUGIN.parse_admin(
        {"prompt_cs": ["Q"], "accepted_1_cs": ["a"], "ignore_diacritics": ["on"]}, ["cs"]
    )
    assert config["ignore_case"] is False and config["ignore_spaces"] is False
    assert config["ignore_diacritics"] is True


def test_a_marker_used_twice_is_refused():
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(prompt_cs="{1} a {1}"), ["cs"])
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form(prompt_cs="{1} a {01}"), ["cs"])
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(one_field(prompt={"cs": "{1} a {1}"}), "cs")
