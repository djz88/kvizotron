import json

import pytest
from django.utils import translation

from app.contracts import AdminFormError, CsvRowError, ItemGrade
from app.plugins.questions.matching.plugin import MAX_ITEMS, MatchingQuestion
from tests.contracts.question_type import HOSTILE, QuestionTypeContract

PLUGIN = MatchingQuestion()
I1, I2, I3 = "1111aaaa", "2222bbbb", "3333cccc"
M1, M2, M3 = "f1f1f1f1", "e2e2e2e2", "d3d3d3d3"


def pairs(**fields):
    return {
        "prompt": {"cs": "Spojte", "uk": "З'єднайте"},
        "mode": "pairs",
        "items": [
            {
                "id": I1,
                "match_id": M1,
                "text": {"cs": "A", "uk": "А"},
                "match": {"cs": "1", "uk": "1"},
            },
            {
                "id": I2,
                "match_id": M2,
                "text": {"cs": "B", "uk": "Б"},
                "match": {"cs": "2", "uk": "2"},
            },
            {
                "id": I3,
                "match_id": M3,
                "text": {"cs": "C", "uk": "В"},
                "match": {"cs": "3", "uk": "3"},
            },
        ],
        **fields,
    }


def order(direction="top_down", **fields):
    return {
        "prompt": {"cs": "Seřaďte", "uk": "Упорядкуйте"},
        "mode": "order",
        "direction": direction,
        "items": [
            {"id": I2, "text": {"cs": "První", "uk": "Перший"}},
            {"id": I3, "text": {"cs": "Druhá", "uk": "Другий"}},
            {"id": I1, "text": {"cs": "Třetí", "uk": "Третій"}},
        ],
        **fields,
    }


def changed_pair_text():
    config = pairs()
    config["items"][0]["match"]["cs"] = "9"
    return config


def changed_left_text():
    config = pairs()
    config["items"][0]["text"]["cs"] = "Z"
    return config


def swapped_order():
    config = order()
    config["items"].reverse()
    return config


CSV_BAD = [
    {"prompt_cs": "", "config_json": '{"mode": "pairs", "items": []}'},
    {"prompt_cs": "Q", "config_json": "not json"},
    {"prompt_cs": "Q", "config_json": "[1, 2]"},
    {"prompt_cs": "Q", "config_json": '{"mode": "pairs", "items": "x"}'},
    {"prompt_cs": "Q", "config_json": '{"mode": "pairs", "items": [{"text": {"cs": "A"}}]}'},
    {"prompt_cs": "Q", "config_json": '{"mode": "x", "items": []}'},
]


class TestMatchingPairs(QuestionTypeContract):
    csv_bad_cells = CSV_BAD
    plugin = PLUGIN
    definition = pairs()
    answer_key_values = ['"match_id"', '"correct"']
    valid_answer = {f"pair_{I1}": M2}
    correct_answer = {f"pair_{I1}": M1, f"pair_{I2}": M2, f"pair_{I3}": M3}
    malformed_answers = [
        {f"pair_{I1}": "nope"},
        {"pair_unknown": M1},
        {f"pair_{I1}": [M1]},
        {f"pair_{I1}": 3},
        "x",
        None,
    ]
    admin_form = {
        "mode": ["pairs"],
        "prompt_cs": ["Spojte"],
        "item_0_cs": ["A"],
        "match_0_cs": ["1"],
        "item_1_cs": ["B"],
        "match_1_cs": ["2"],
    }
    changed_definitions = [
        {**pairs(), "prompt": {"cs": "Jiné", "uk": "Інше"}},
        changed_left_text(),
        changed_pair_text(),
        order(),
    ]
    answer_marker = "selected"
    solution_marker = "reveal-correct"
    hostile_definition = {
        "prompt": {"cs": HOSTILE},
        "mode": "pairs",
        "items": [
            {"id": "a", "match_id": "x", "text": {"cs": HOSTILE}, "match": {"cs": HOSTILE}},
            {"id": "b", "match_id": "y", "text": {"cs": HOSTILE}, "match": {"cs": HOSTILE}},
        ],
    }


class TestMatchingOrder(QuestionTypeContract):
    csv_bad_cells = CSV_BAD
    plugin = PLUGIN
    definition = order()
    answer_key_values = ['"correct"']
    valid_answer = {"order": [I1, I2, I3]}
    correct_answer = {"order": [I2, I3, I1]}
    malformed_answers = [
        {"order": "x"},
        {"order": [1, 2, 3]},
        {"order": [I1, I2]},
        {"order": [I1, I1, I2]},
        {"order": [I1, I2, "nope"]},
        {f"pos_{I1}": "1", f"pos_{I2}": "1"},
        {f"pos_{I1}": "9"},
        {f"pos_{I1}": "x"},
        {f"pos_{I1}": ["1"]},
        {"pos_unknown": "1"},
        None,
    ]
    admin_form = {
        "mode": ["order"],
        "prompt_cs": ["Seřaďte"],
        "item_0_cs": ["A"],
        "item_1_cs": ["B"],
    }
    changed_definitions = [
        {**order(), "prompt": {"cs": "Jiné", "uk": "Інше"}},
        swapped_order(),
        order("bottom_up"),
    ]
    answer_marker = "selected"
    solution_marker = "reveal-correct"
    hostile_definition = {
        "prompt": {"cs": HOSTILE},
        "mode": "order",
        "direction": "top_down",
        "items": [{"id": "a", "text": {"cs": HOSTILE}}, {"id": "b", "text": {"cs": HOSTILE}}],
    }


def html(config, answer=None, locale="cs"):
    payload = PLUGIN.public_payload(config, locale)
    return PLUGIN.render_public({**payload, "id": "q1"}, locale, answer)


def test_pairs_grade():
    answer = {f"pair_{I1}": M1, f"pair_{I2}": M2, f"pair_{I3}": ""}
    assert PLUGIN.grade(pairs(), answer) == ItemGrade(2, 0, 3)
    assert PLUGIN.grade(pairs(), {f"pair_{I1}": M2, f"pair_{I2}": M1}) == ItemGrade(0, 0, 3)


def test_unanswered_pair_is_not_right():
    assert PLUGIN.grade(pairs(), {f"pair_{I1}": M1, f"pair_{I2}": ""}) == ItemGrade(1, 0, 3)


def test_two_rows_cannot_choose_one_text():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(pairs(), {f"pair_{I1}": M1, f"pair_{I2}": M1})


def test_two_rows_left_blank_are_fine():
    PLUGIN.validate_submission(pairs(), {f"pair_{I1}": "", f"pair_{I2}": ""})


def test_pairs_say_each_choice_is_used_once():
    with translation.override("cs"):
        page = html(pairs())
    assert "data-unique-choices" in page and "jen jednou" in page


def test_blank_pair_is_a_valid_answer():
    PLUGIN.validate_submission(pairs(), {f"pair_{I1}": ""})


def test_order_grade_top_down():
    assert PLUGIN.grade(order(), {"order": [I2, I3, I1]}) == ItemGrade(3, 0, 3)
    assert PLUGIN.grade(order(), {"order": [I2, I1, I3]}) == ItemGrade(1, 0, 3)


def test_order_grade_bottom_up_expects_reversed():
    bottom_up = order("bottom_up")
    assert PLUGIN.grade(bottom_up, {"order": [I1, I3, I2]}) == ItemGrade(3, 0, 3)
    assert PLUGIN.grade(bottom_up, {"order": [I2, I3, I1]}).right == 1


@pytest.mark.parametrize("direction", ["top_down", "bottom_up"])
def test_no_js_positions_grade_like_the_order_list(direction):
    config = order(direction)
    listed = [I1, I3, I2]
    positions = {f"pos_{item}": str(number) for number, item in enumerate(listed, start=1)}
    PLUGIN.validate_submission(config, positions)
    assert PLUGIN.grade(config, positions) == PLUGIN.grade(config, {"order": listed})


def test_blank_positions_are_unanswered_not_wrong():
    answer = {f"pos_{I2}": "1", f"pos_{I3}": "", f"pos_{I1}": ""}
    PLUGIN.validate_submission(order(), answer)
    assert PLUGIN.grade(order(), answer) == ItemGrade(1, 0, 3)


def test_repeated_position_is_refused():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(order(), {f"pos_{I1}": "2", f"pos_{I2}": "2"})


@pytest.mark.parametrize("position", ["0", "4", "-1", "1.5", "٣", ""])
def test_position_out_of_range_is_refused(position):
    answer = {f"pos_{I1}": position}
    if position == "":
        PLUGIN.validate_submission(order(), answer)  # a position not chosen yet
        return
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(order(), answer)


def test_unknown_item_is_refused():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(pairs(), {"pair_cccc9999": M1})
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(order(), {"order": [I1, I2, "cccc9999"]})


@pytest.mark.parametrize("answer", [{"options": ["a"]}, {"none": "1"}, {}])
def test_answer_of_another_type_is_harmless(answer):
    for config in (pairs(), order()):
        try:
            PLUGIN.validate_submission(config, answer)
        except ValueError:
            continue
        assert PLUGIN.grade(config, answer).right == 0


def test_payload_order_does_not_depend_on_correct_order():
    rotated = pairs()
    rotated["items"] = rotated["items"][1:] + rotated["items"][:1]
    assert PLUGIN.public_payload(pairs(), "cs") == PLUGIN.public_payload(rotated, "cs")
    assert PLUGIN.public_payload(order(), "cs") == PLUGIN.public_payload(swapped_order(), "cs")


def test_a_pair_is_not_visible_in_the_payload():
    payload = PLUGIN.public_payload(pairs(), "cs")
    assert {i["id"] for i in payload["items"]}.isdisjoint({c["id"] for c in payload["choices"]})
    assert "match" not in json.dumps(payload["items"])


def test_right_hand_texts_are_not_in_the_order_of_the_rows():
    payload = PLUGIN.public_payload(pairs(), "cs")
    assert [i["text"] for i in payload["items"]] == ["A", "B", "C"]
    assert [c["text"] for c in payload["choices"]] == ["3", "2", "1"]


def test_order_html_does_not_depend_on_correct_order():
    assert html(order()) == html(swapped_order())


def test_order_is_a_sortable_list_with_position_selects():
    page = html(order())
    assert "data-sortable" in page
    assert f'name="q1:pos_{I1}"' in page


def test_direction_is_shown_to_the_participant():
    with translation.override("cs"):
        assert "shora dolů" in html(order())
        assert "zdola nahoru" in html(order("bottom_up"))


def test_render_public_keeps_pairs_and_order():
    page = html(pairs(), {f"pair_{I1}": M2})
    assert f'value="{M2}" selected' in page
    kept = html(order(), {"order": [I3, I1, I2]})
    assert kept.index(f'name="q1:pos_{I3}"') < kept.index(f'name="q1:pos_{I1}"')
    assert kept.index(f'name="q1:pos_{I1}"') < kept.index(f'name="q1:pos_{I2}"')
    assert kept.count("selected") == 3


def test_render_public_keeps_positions_sent_without_a_script():
    page = html(order(), {f"pos_{I1}": "2", f"pos_{I2}": "2"})
    assert page.count("selected") == 2


def test_fewer_than_two_items_cannot_be_published():
    config = pairs()
    config["items"] = config["items"][:1]
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")


def test_two_right_texts_alike_are_refused():
    config = pairs()
    config["items"][1]["match"]["cs"] = " 1 "
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")
    PLUGIN.validate_definition(config, "uk")
    form = TestMatchingPairs.admin_form | {"match_1_cs": ["1"]}
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form, ["cs"])


def test_two_left_texts_alike_are_refused():
    config = order()
    config["items"][1]["text"]["cs"] = "první"
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")


def test_definition_incomplete_in_a_language_is_refused():
    config = pairs()
    config["items"][0]["match"]["uk"] = ""
    PLUGIN.validate_definition(config, "cs")
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "uk")


def test_parse_keeps_ids_drops_blank_rows_and_gives_random_match_ids():
    form = TestMatchingPairs.admin_form | {
        "item_0_id": [I1],
        "item_0_match_id": [M1],
        "item_2_cs": ["C"],
        "match_2_cs": ["3"],
    }
    config = PLUGIN.parse_admin(form, ["cs"])
    assert [item["text"]["cs"] for item in config["items"]] == ["A", "B", "C"]
    assert config["items"][0]["id"] == I1 and config["items"][0]["match_id"] == M1
    other = config["items"][1]
    assert (
        len(other["id"]) == 8 and len(other["match_id"]) == 8 and other["id"] != other["match_id"]
    )


def test_parse_refuses_a_row_with_only_one_side():
    form = TestMatchingPairs.admin_form | {"item_2_cs": ["C"]}
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(form, ["cs"])
    assert error.value.config["prompt"] == {"cs": "Spojte"}
    form = TestMatchingPairs.admin_form | {"match_2_cs": ["3"]}
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form, ["cs"])


def test_parse_order_keeps_rows_in_the_correct_order_and_the_direction():
    form = TestMatchingOrder.admin_form | {"direction": ["bottom_up"]}
    config = PLUGIN.parse_admin(form, ["cs"])
    assert [item["text"]["cs"] for item in config["items"]] == ["A", "B"]
    assert config["direction"] == "bottom_up"
    assert "match" not in config["items"][0]


def test_parse_of_unknown_mode_and_direction_uses_defaults():
    config = PLUGIN.parse_admin({"mode": ["x"], "direction": ["y"], "prompt_cs": ["Q"]}, ["cs"])
    assert config["mode"] == "pairs"
    config = PLUGIN.parse_admin({"mode": ["order"], "direction": ["y"], "prompt_cs": ["Q"]}, ["cs"])
    assert config["direction"] == "top_down"


def test_admin_form_shows_saved_values():
    page = PLUGIN.render_admin(pairs(), ["cs", "uk"])
    assert (
        f'name="item_0_id" value="{I1}"' in page and f'name="item_0_match_id" value="{M1}"' in page
    )
    assert 'name="item_7_cs"' in page and 'name="match_7_uk"' in page
    assert 'value="pairs" checked' in page
    assert 'value="bottom_up" checked' in PLUGIN.render_admin(order("bottom_up"), ["cs"])


def test_scoring_offers_both_strategies():
    assert list(PLUGIN.available_scoring_strategies()) == ["all_or_nothing", "partial"]


def test_describe_survives_an_incomplete_draft():
    assert PLUGIN.describe_definition({"prompt": {}, "items": []}, ["cs"])


def test_matching_ignores_the_seed():
    for config in (pairs(), order()):
        assert PLUGIN.public_payload(config, "cs", {"shuffle_seed": "x"}) == PLUGIN.public_payload(
            config, "cs"
        )


def test_solution_of_pairs_shows_pairs_and_a_wrong_choice():
    html = PLUGIN.render_solution(pairs(), "cs", {f"pair_{I1}": M2})
    assert "A" in html
    assert html.count("reveal-correct") == 3
    assert html.count("reveal-theirs") == 1


def test_solution_of_order_lists_the_correct_order():
    html = PLUGIN.render_solution(order(), "cs", None)
    texts = [item["text"]["cs"] for item in order()["items"]]
    assert html.index(texts[0]) < html.index(texts[1]) < html.index(texts[2])


def test_solution_of_bottom_up_order_reverses():
    html = PLUGIN.render_solution(order(direction="bottom_up"), "cs", None)
    texts = [item["text"]["cs"] for item in order()["items"]]
    assert html.index(texts[2]) < html.index(texts[0])


def test_csv_error_names_the_config_column():
    with pytest.raises(CsvRowError) as error:
        PLUGIN.from_csv({"prompt_cs": "Q", "config_json": "not json"}, ["cs"])
    assert error.value.column == "config_json"


def test_csv_more_items_than_allowed_refused():
    items = [{"text": {"cs": str(i)}, "match": {"cs": f"m{i}"}} for i in range(MAX_ITEMS + 1)]
    cells = {"prompt_cs": "Q", "config_json": json.dumps({"mode": "pairs", "items": items})}
    with pytest.raises(CsvRowError):
        PLUGIN.from_csv(cells, ["cs"])
