import json

import pytest
from django.utils import translation

from app.contracts import AdminFormError, CsvRowError, ItemGrade
from app.plugins.questions.choice.plugin import ChoiceQuestion
from tests.contracts.question_type import HOSTILE, QuestionTypeContract

PLUGIN = ChoiceQuestion()
A, B, C = "aaaa1111", "bbbb2222", "cccc3333"
ALL_QUESTIONS = {"none_option": "all_questions"}
TRICK_QUESTIONS = {"none_option": "trick_questions"}


def several(correct=(A, B), **fields):
    return definition(correct, allow_multiple=True, **fields)


def definition(correct=(A,), prompt_uk="Питання", option_uk="Так", **fields):
    return {
        "prompt": {"cs": "Otázka", "uk": prompt_uk},
        "options": [
            {"id": A, "text": {"cs": "Ano", "uk": option_uk}},
            {"id": B, "text": {"cs": "Ne", "uk": "Ні"}},
            {"id": C, "text": {"cs": "Možná", "uk": "Може"}},
        ],
        "correct": list(correct),
        "reveal_count": False,
        "kind": "standard",
        **fields,
    }


def yes_no(correct=(A,)):
    config = definition(correct, kind="yes_no")
    config["options"] = config["options"][:2]
    return config


def with_changed_option_text():
    config = definition()
    config["options"][0]["text"]["cs"] = "Jinak"
    return config


def with_changed_prompt():
    config = definition()
    config["prompt"]["cs"] = "Jiná otázka"
    return config


def with_swapped_options():
    config = definition()
    config["options"].reverse()
    return config


class TestChoice(QuestionTypeContract):
    plugin = PLUGIN
    csv_bad_cells = [
        {"prompt_cs": "", "option_1_cs": "A", "option_2_cs": "B", "correct": "A"},
        {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "B", "correct": "Z"},
        {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "B", "correct": "1"},
        {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "", "correct": "B"},
        {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "A", "correct": "A"},
        {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "B", "allow_multiple": "maybe"},
        {
            "prompt_cs": "Q",
            "option_1_cs": "A",
            "option_2_cs": "B",
            "correct": "A,B",
            "kind": "yes_no",
        },
    ]
    changed_definitions = [
        with_changed_prompt(),
        with_changed_option_text(),
        with_swapped_options(),
        definition(correct=(B,)),
        several((A,), reveal_count=True),
        several((A,)),
        yes_no(),
    ]
    answer_marker = "checked"
    solution_marker = "Ano"
    hostile_definition = {
        "prompt": {"cs": HOSTILE},
        "options": [{"id": "a", "text": {"cs": HOSTILE}}, {"id": "b", "text": {"cs": HOSTILE}}],
        "correct": ["a"],
    }
    definition = definition()
    answer_key_values = ['"correct"']
    valid_answer = {"options": [B]}
    correct_answer = {"options": [A]}
    malformed_answers = [
        {"options": 3},
        {"options": "aaaa1111"},
        {"options": [1]},
        {"options": ["nope"]},
        {"options": [A, "nope"]},
        {"none": "yes"},
        {"none": ["1"]},
        {"options": [A, B]},
        {"options": [A], "none": "1"},
        "aaaa1111",
        None,
    ]
    admin_form = {
        "prompt_cs": ["Otázka"],
        "option_0_cs": ["Ano"],
        "option_1_cs": ["Ne"],
        "correct_1": ["on"],
    }


def public(correct=(A,), locale="cs", quiz_settings=None, **fields):
    return PLUGIN.public_payload(definition(correct, **fields), locale, quiz_settings)


def public_several(correct=(A, B), locale="cs", quiz_settings=None, **fields):
    return PLUGIN.public_payload(several(correct, **fields), locale, quiz_settings)


def html(payload, answer=None):
    return PLUGIN.render_public({**payload, "id": "q1"}, "cs", answer)


def test_two_correct_of_three():
    grade = PLUGIN.grade(several(), {"options": [A, B]})
    assert grade == ItemGrade(2, 0, 2)


def test_wrong_tick_counts():
    assert PLUGIN.grade(several(), {"options": [A, C]}) == ItemGrade(1, 1, 2)


def test_ticking_everything_counts_the_wrong_ones():
    assert PLUGIN.grade(several(), {"options": [A, B, C]}) == ItemGrade(2, 1, 2)


def test_a_repeated_tick_counts_once():
    assert PLUGIN.grade(several(), {"options": [A, A]}) == ItemGrade(1, 0, 2)


def test_trick_scores_only_with_none():
    trick = definition(())
    assert PLUGIN.grade(trick, {"none": "1"}) == ItemGrade(1, 0, 1)
    assert PLUGIN.grade(trick, {}) == ItemGrade(0, 0, 1)
    assert PLUGIN.grade(trick, {"options": [A]}) == ItemGrade(0, 1, 1)
    assert PLUGIN.grade(trick, {"options": [A], "none": "1"}).right == 0


def test_none_on_a_question_with_answers_scores_zero():
    assert PLUGIN.grade(definition((A,)), {"none": "1"}).right == 0
    assert PLUGIN.grade(definition((A,)), {"none": "1", "options": [A]}).right == 0


def test_nothing_ticked_scores_zero():
    assert PLUGIN.grade(definition((A,)), {}) == ItemGrade(0, 0, 1)


def test_nothing_ticked_is_a_valid_answer():
    PLUGIN.validate_submission(definition(), {})


def test_unknown_option_is_refused():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(definition(), {"options": ["cccc9999"]})


@pytest.mark.parametrize("answer", [{"options": "a"}, {"options": [1]}, {"pair_x": "y"}, []])
def test_answer_of_wrong_shape_is_refused_or_harmless(answer):
    try:
        PLUGIN.validate_submission(definition(), answer)
    except ValueError:
        return
    assert PLUGIN.grade(definition(), answer).right == 0


def test_public_payload_has_no_correct_list_and_says_how_many_only_if_revealed():
    hidden = public_several()
    assert "correct" not in json.dumps(hidden)
    assert "count" not in hidden
    assert public_several(reveal_count=True)["count"] == 2


def test_public_payload_does_not_depend_on_which_options_are_correct():
    assert public((A,)) == public((B,))
    assert public_several((A,), reveal_count=True) == public_several((B,), reveal_count=True)
    assert public((A,), quiz_settings=TRICK_QUESTIONS) == public(
        (B,), quiz_settings=TRICK_QUESTIONS
    )


def test_public_payload_is_in_the_requested_language():
    assert public(locale="uk")["prompt"] == "Питання"
    assert public(locale="uk")["options"][1] == {"id": B, "text": "Ні"}


def test_render_public_does_not_depend_on_correct_option():
    assert html(public((A,))) == html(public((B,)))


def test_trick_question_shows_no_hint_even_with_reveal_on():
    payload = public_several((), reveal_count=True)
    assert "count" not in payload
    assert html(payload) == html(public_several(()))


def test_hint_is_shown_when_revealed():
    with translation.override("cs"):
        assert "vyberte 2" in html(public_several(reveal_count=True))


def test_several_answers_use_checkboxes_for_any_number_of_correct_answers():
    for correct in ((A,), (A, B), ()):
        page = html(public_several(correct))
        assert 'type="checkbox"' in page
        assert 'type="radio"' not in page
        assert 'name="q1:options[]"' in page


def test_one_answer_is_the_default_and_uses_radio_buttons():
    for config in (definition((A,)), definition(()), yes_no()):
        page = html(PLUGIN.public_payload(config, "cs"))
        assert 'type="radio"' in page and 'type="checkbox"' not in page
        assert 'name="q1:options[]"' in page


def test_one_answer_never_shows_a_number():
    assert "count" not in public((A,), reveal_count=True)


def test_two_ticks_are_refused_when_one_answer_is_allowed():
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(definition((A,)), {"options": [A, B]})
    with pytest.raises(ValueError):
        PLUGIN.validate_submission(yes_no(), {"options": [A, B]})
    PLUGIN.validate_submission(several(), {"options": [A, B]})


def test_a_repeated_tick_is_one_answer():
    PLUGIN.validate_submission(definition((A,)), {"options": [A, A]})


def test_several_correct_need_several_answers_allowed():
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(definition((A, B)), "cs")
    PLUGIN.validate_definition(several(), "cs")


def test_parse_refuses_several_correct_when_one_answer_is_allowed():
    form = {
        "prompt_cs": ["Q"],
        "option_0_cs": ["A"],
        "option_1_cs": ["B"],
        "correct_0": ["on"],
        "correct_1": ["on"],
    }
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(form, ["cs"])
    assert len(error.value.config["correct"]) == 2
    assert PLUGIN.parse_admin(form | {"allow_multiple": ["on"]}, ["cs"])["allow_multiple"] is True


def test_parse_ignores_the_reveal_box_when_one_answer_is_allowed():
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": ["B"], "reveal_count": ["on"]}
    assert PLUGIN.parse_admin(form, ["cs"])["reveal_count"] is False


def test_admin_form_offers_several_answers_unticked_by_default():
    page = PLUGIN.render_admin({}, ["cs"])
    assert 'name="allow_multiple"' in page and 'name="allow_multiple" checked' not in page
    assert 'name="allow_multiple" checked' in PLUGIN.render_admin(several(), ["cs"])


def test_none_is_one_of_the_radio_buttons_and_scores_on_a_trick_question():
    page = html(public((), quiz_settings=ALL_QUESTIONS))
    assert 'type="radio" data-none name="q1:options[]" value="none"' in page
    PLUGIN.validate_submission(definition(()), {"options": ["none"]})
    assert PLUGIN.grade(definition(()), {"options": ["none"]}) == ItemGrade(1, 0, 1)
    assert PLUGIN.grade(definition((A,)), {"options": ["none"]}).right == 0


def test_render_public_keeps_the_chosen_radio_button():
    chosen = html(public(quiz_settings=ALL_QUESTIONS), {"options": ["none"]})
    assert 'value="none" checked' in chosen
    assert f'value="{B}" checked' in html(public(), {"options": [B]})


def test_none_is_offered_when_payload_says_so():
    assert 'name="q1:none"' in html(public_several(quiz_settings=ALL_QUESTIONS))


def test_none_is_not_offered_without_a_quiz_setting():
    assert 'name="q1:none"' not in html(public_several())
    assert 'value="none"' not in html(public())


def test_none_follows_the_quiz_setting_on_trick_questions():
    assert public((), quiz_settings=TRICK_QUESTIONS)["offer_none"] is True
    assert public((A,), quiz_settings=TRICK_QUESTIONS)["offer_none"] is False
    assert public((), quiz_settings=ALL_QUESTIONS)["offer_none"] is True
    assert public((A,), quiz_settings=ALL_QUESTIONS)["offer_none"] is True


def test_none_text_is_translated():
    with translation.override("uk"):
        assert "Жодна з відповідей" in html(public(quiz_settings=ALL_QUESTIONS))


def test_yes_no_never_offers_none():
    for quiz_settings in (ALL_QUESTIONS, TRICK_QUESTIONS):
        assert PLUGIN.public_payload(yes_no(), "cs", quiz_settings)["offer_none"] is False


def test_yes_no_never_reveals_a_count():
    assert "count" not in PLUGIN.public_payload({**yes_no(), "reveal_count": True}, "cs")


def test_yes_no_needs_exactly_one_correct():
    for correct in ((), (A, B)):
        with pytest.raises(ValueError):
            PLUGIN.validate_definition(yes_no(correct), "cs")
    PLUGIN.validate_definition(yes_no(), "cs")


def yes_no_form(*correct):
    form = {"kind": ["yes_no"], "prompt_cs": ["Q"], "option_0_cs": ["Ano"], "option_1_cs": ["Ne"]}
    return form | {f"correct_{row}": ["on"] for row in correct}


@pytest.mark.parametrize("correct", [(), (0, 1)])
def test_parse_refuses_yes_no_without_exactly_one_correct(correct):
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(yes_no_form(*correct), ["cs"])
    assert error.value.config["kind"] == "yes_no"


def test_parse_keeps_yes_no():
    config = PLUGIN.parse_admin(yes_no_form(1), ["cs"])
    assert config["kind"] == "yes_no"
    assert config["correct"] == [config["options"][1]["id"]]


def test_initial_yes_no_is_translated_in_every_language():
    config = PLUGIN.initial("yes_no", ["cs", "en", "uk"])
    assert config["kind"] == "yes_no"
    assert [o["text"]["cs"] for o in config["options"]] == ["Ano", "Ne"]
    assert [o["text"]["en"] for o in config["options"]] == ["Yes", "No"]
    assert [o["text"]["uk"] for o in config["options"]] == ["Так", "Ні"]
    assert config["correct"] == []


def test_initial_of_an_unknown_preset_is_empty():
    assert PLUGIN.initial("nope", ["cs"]) == {}


def test_presets_name_yes_no():
    assert [preset["id"] for preset in PLUGIN.presets()] == ["yes_no"]


def test_yes_no_editor_has_two_rows_and_no_reveal_box():
    page = PLUGIN.render_admin(PLUGIN.initial("yes_no", ["cs"]), ["cs"])
    assert 'name="option_1_cs"' in page and 'name="option_2_cs"' not in page
    assert 'name="reveal_count"' not in page
    assert 'name="kind" value="yes_no"' in page


def test_scoring_offers_both_strategies():
    assert list(PLUGIN.available_scoring_strategies()) == ["all_or_nothing", "partial"]


def test_render_public_keeps_ticks_and_none():
    page = html(public_several(quiz_settings=ALL_QUESTIONS), {"options": [B, C], "none": "1"})
    assert f'value="{B}" checked' in page
    assert f'value="{C}" checked' in page
    assert f'value="{A}" checked' not in page
    assert 'name="q1:none" value="1" checked' in page


def test_public_inputs_are_named_by_question_id():
    page = html(public())
    assert 'name="q1:options[]"' in page and f'value="{B}"' in page


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
        PLUGIN.validate_definition(definition(correct=("cccc9999",)), "cs")


def test_trick_definition_is_valid():
    PLUGIN.validate_definition(definition(()), "cs")


def test_parse_keeps_existing_option_ids_and_drops_blank_rows():
    config = PLUGIN.parse_admin(
        {
            "prompt_cs": ["Otázka"],
            "option_0_id": [A],
            "option_0_cs": [" Ano "],
            "option_1_cs": [""],
            "option_2_id": [B],
            "option_2_cs": ["Ne"],
            "correct_2": ["on"],
        },
        ["cs"],
    )
    assert [o["id"] for o in config["options"]] == [A, B]
    assert config["options"][0]["text"] == {"cs": "Ano"}
    assert config["correct"] == [B]


def test_parse_keeps_several_correct_options_and_the_reveal_box():
    config = PLUGIN.parse_admin(
        {
            "prompt_cs": ["Q"],
            "option_0_cs": ["A"],
            "option_1_cs": ["B"],
            "option_2_cs": ["C"],
            "correct_0": ["on"],
            "correct_2": ["on"],
            "reveal_count": ["on"],
            "allow_multiple": ["on"],
        },
        ["cs"],
    )
    ids = [o["id"] for o in config["options"]]
    assert config["correct"] == [ids[0], ids[2]]
    assert config["reveal_count"] is True
    assert config["kind"] == "standard"


def test_parse_without_correct_marks_makes_a_trick_question():
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": ["B"]}
    assert PLUGIN.parse_admin(form, ["cs"])["correct"] == []


def test_parse_refuses_a_correct_mark_on_a_blank_row():
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": [""], "correct_1": ["on"]}
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(form, ["cs"])
    assert error.value.config["prompt"] == {"cs": "Q"}


def test_parse_of_an_unknown_kind_is_standard():
    form = {"kind": ["nope"], "prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": ["B"]}
    assert PLUGIN.parse_admin(form, ["cs"])["kind"] == "standard"


def test_parse_generates_random_ids_for_new_rows():
    form = {"prompt_cs": ["Q"], "option_0_cs": ["A"], "option_1_cs": ["B"], "correct_0": ["on"]}
    first = PLUGIN.parse_admin(form, ["cs"])["options"]
    second = PLUGIN.parse_admin(form, ["cs"])["options"]
    assert first[0]["id"] != first[1]["id"]
    assert first[0]["id"] != second[0]["id"]
    assert len(first[0]["id"]) == 8


def test_admin_form_shows_saved_values():
    page = PLUGIN.render_admin(definition(correct=(B,)), ["cs", "uk"])
    assert 'value="Otázka"' in page and 'value="Питання"' in page
    assert 'name="option_5_cs"' in page
    assert 'name="correct_1" checked' in page
    assert 'name="correct_0" checked' not in page


def test_admin_form_keeps_the_reveal_box():
    assert 'name="reveal_count" checked' in PLUGIN.render_admin(several(reveal_count=True), ["cs"])


def test_admin_form_explains_the_trick_question_and_hint():
    with translation.override("cs"):
        page = PLUGIN.render_admin(definition(), ["cs"])
    assert "chyták" in page


def test_plugin_label_follows_active_language():
    with translation.override("en"):
        english = PLUGIN.render_admin(definition(), ["cs"])
    with translation.override("cs"):
        czech = PLUGIN.render_admin(definition(), ["cs"])
    assert "Options" in english and "Možnosti" in czech


def test_describe_marks_the_correct_options():
    rows = {(r.key, r.locale): r for r in PLUGIN.describe_definition(definition(), ["cs", "uk"])}
    assert rows[("correct", None)].value == "1: Ano"
    other = PLUGIN.describe_definition(several((B, C)), ["cs", "uk"])
    assert {(r.key, r.locale): r for r in other}[("correct", None)].value == "2: Ne, 3: Možná"


def test_describe_says_a_trick_question_has_none():
    with translation.override("en"):
        rows = {r.key: r.value for r in PLUGIN.describe_definition(definition(()), ["cs"])}
    assert rows["correct"] == "None (trick question)"


def test_describe_covers_each_locale():
    described = PLUGIN.describe_definition(definition(), ["cs", "uk"])
    rows = {(r.key, r.locale): r.value for r in described}
    assert rows[("prompt", "uk")] == "Питання"
    assert rows[(f"option:{A}", "uk")] == "Так"
    assert rows[("prompt", "cs")] == "Otázka"


def test_describe_tells_equal_option_texts_apart():
    config = definition()
    config["options"][1]["text"]["cs"] = "Ano"
    first = PLUGIN.describe_definition(config, ["cs"])
    config["correct"] = [B]
    assert PLUGIN.describe_definition(config, ["cs"]) != first


def test_describe_follows_active_language():
    with translation.override("cs"):
        labels = {r.key: r.label for r in PLUGIN.describe_definition(definition(), ["cs"])}
    assert labels["prompt"] == "Otázka"


def test_describe_survives_an_incomplete_draft():
    assert PLUGIN.describe_definition({"prompt": {}, "options": [], "correct": []}, ["cs"])


def two_rows(first, second, locale="cs"):
    return {
        "prompt_cs": ["Otázka"],
        f"option_0_{locale}": [first],
        f"option_1_{locale}": [second],
        "correct_0": ["on"],
    }


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Ano", "Ano"),
        ("Ano", "ano"),
        ("Ano", "  Ano "),
        ("Ano ano", "Ano   ano"),
        ("Straße", "STRASSE"),
    ],
)
def test_parse_refuses_two_options_with_the_same_text(first, second):
    with pytest.raises(AdminFormError) as error:
        PLUGIN.parse_admin(two_rows(first, second), ["cs"])
    assert error.value.config["options"][1]["text"]["cs"] == second.strip()


def test_parse_accepts_different_options():
    assert len(PLUGIN.parse_admin(two_rows("Ano", "Ne"), ["cs"])["options"]) == 2


def test_parse_ignores_the_same_blank_text_in_a_language_not_yet_translated():
    form = two_rows("Ano", "Ne") | {"option_0_en": [""], "option_1_en": [""]}
    assert len(PLUGIN.parse_admin(form, ["cs", "en"])["options"]) == 2


def test_parse_refuses_the_same_text_in_any_language():
    form = two_rows("Ano", "Ne") | {"option_0_en": ["Yes"], "option_1_en": ["yes"]}
    with pytest.raises(AdminFormError):
        PLUGIN.parse_admin(form, ["cs", "en"])


def test_definition_with_the_same_option_text_cannot_be_published():
    config = definition()
    config["options"][1]["text"]["cs"] = "ano"
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "cs")
    PLUGIN.validate_definition(config, "uk")  # only the affected language


def test_same_text_in_two_languages_is_fine():
    config = definition(option_uk="Ano")
    PLUGIN.validate_definition(config, "cs")


def image(asset="asset-1", cs="Popis", uk="Опис"):
    return {"asset": asset, "alt": {"cs": cs, "uk": uk}}


def with_prompt_image(**alts):
    return definition(image=image(**alts))


def with_option_image(**alts):
    config = definition()
    config["options"][1]["image"] = image(**alts)
    return config


def image_only_option():
    config = definition()
    config["options"][1] = {"id": B, "text": {"cs": "", "uk": ""}, "image": image()}
    return config


def test_public_payload_has_the_image_with_alt_in_the_language():
    assert PLUGIN.public_payload(with_prompt_image(), "uk")["image"] == {
        "asset": "asset-1",
        "alt": "Опис",
    }
    option = PLUGIN.public_payload(with_option_image(), "cs")["options"][1]
    assert option["image"] == {"asset": "asset-1", "alt": "Popis"}


def test_render_public_shows_images_lazily_with_alt():
    payload = PLUGIN.public_payload(with_prompt_image(), "cs")
    payload["image"] = {"url": "/media/x", "alt": "Popis"}
    page = html(payload)
    assert '<img src="/media/x" alt="Popis" loading="lazy"' in page


def test_render_public_shows_option_image():
    payload = PLUGIN.public_payload(with_option_image(), "cs")
    payload["options"][1]["image"] = {"url": "/media/y", "alt": "Popis"}
    assert '<img src="/media/y" alt="Popis" loading="lazy"' in html(payload)


def test_hostile_alt_text_is_escaped():
    payload = PLUGIN.public_payload(with_prompt_image(cs=HOSTILE), "cs")
    payload["image"]["url"] = "/media/x"
    assert "<script>x" not in html(payload)
    page = PLUGIN.render_admin(with_prompt_image(cs=HOSTILE), ["cs"])
    assert "<script>x" not in page and "&lt;script&gt;x" in page or "&#34;&gt;&lt;script" in page


@pytest.mark.parametrize(
    "config", [with_prompt_image(uk=""), with_option_image(uk="")], ids=["prompt", "option"]
)
def test_missing_alternative_text_blocks_the_language(config):
    PLUGIN.validate_definition(config, "cs")
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "uk")


def test_alternative_text_of_a_language_added_later_is_missing():
    config = with_prompt_image()
    config["prompt"]["en"] = "Question"
    for option in config["options"]:
        option["text"]["en"] = option["text"]["cs"]
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "en")


def test_option_may_have_only_an_image():
    PLUGIN.validate_definition(image_only_option(), "cs")
    PLUGIN.validate_definition(image_only_option(), "uk")


def test_option_with_text_in_one_language_needs_it_in_the_others_even_with_an_image():
    config = with_option_image()
    config["options"][1]["text"]["uk"] = ""
    PLUGIN.validate_definition(config, "cs")
    with pytest.raises(ValueError):
        PLUGIN.validate_definition(config, "uk")


def test_option_with_neither_is_dropped():
    form = {
        "prompt_cs": ["Q"],
        "option_0_cs": ["A"],
        "option_1_cs": [""],
        "option_1_image_alt_cs": ["Popis bez obrázku"],
        "option_2_cs": ["C"],
    }
    assert [o["text"]["cs"] for o in PLUGIN.parse_admin(form, ["cs"])["options"]] == ["A", "C"]


def test_parse_reads_images_and_alts():
    form = {
        "prompt_cs": ["Q"],
        "image_asset": ["id-1"],
        "image_alt_cs": ["Popis"],
        "option_0_cs": ["A"],
        "option_1_cs": [""],
        "option_1_image_asset": ["id-2"],
        "option_1_image_alt_cs": ["Druhý"],
        "correct_1": ["on"],
    }
    config = PLUGIN.parse_admin(form, ["cs"])
    assert config["image"] == {"asset": "id-1", "alt": {"cs": "Popis"}}
    assert config["options"][1]["image"] == {"asset": "id-2", "alt": {"cs": "Druhý"}}
    assert config["correct"] == [config["options"][1]["id"]]


def test_remove_box_clears_an_image():
    form = {
        "prompt_cs": ["Q"],
        "image_asset": ["id-1"],
        "image_remove": ["on"],
        "option_0_cs": ["A"],
        "option_0_image_asset": ["id-2"],
        "option_0_image_remove": ["on"],
        "option_1_cs": ["B"],
    }
    config = PLUGIN.parse_admin(form, ["cs"])
    assert "image" not in config and "image" not in config["options"][0]


def test_admin_form_keeps_an_uploaded_image():
    config = with_prompt_image()
    config["image"]["url"] = "/media/x"
    page = PLUGIN.render_admin(config, ["cs", "uk"])
    assert 'name="image_asset" value="asset-1"' in page
    assert '<img src="/media/x"' in page
    assert 'name="image_alt_uk" value="Опис"' in page
    assert 'name="image_remove"' in page
    assert 'type="file" name="image"' in page
    assert 'type="file" name="option_5_image"' in page


def test_change_of_image_or_alt_changes_the_description():
    rows = PLUGIN.describe_definition(with_prompt_image(), ["cs"])
    assert PLUGIN.describe_definition(with_prompt_image(asset="asset-2"), ["cs"]) != rows
    assert PLUGIN.describe_definition(with_prompt_image(cs="Jiný"), ["cs"]) != rows
    option_rows = PLUGIN.describe_definition(with_option_image(), ["cs"])
    assert PLUGIN.describe_definition(with_option_image(cs="Jiný"), ["cs"]) != option_rows
    assert PLUGIN.describe_definition(definition(), ["cs"]) != rows


def test_same_text_rule_ignores_options_without_text():
    config = image_only_option()
    config["options"][0] = {"id": A, "text": {"cs": "", "uk": ""}, "image": image()}
    PLUGIN.validate_definition(config, "cs")


def test_admin_form_folds_image_fields_until_there_is_an_image():
    empty = PLUGIN.render_admin(definition(), ["cs"])
    assert '<details class="image-fields" open>' not in empty
    assert '<details class="image-fields">' in empty
    assert '<details class="image-fields" open>' in PLUGIN.render_admin(with_prompt_image(), ["cs"])


def _many(**fields):
    config = definition(**fields)
    config["options"] = [
        {"id": f"opt{number}", "text": {"cs": f"Text {number}"}} for number in range(8)
    ]
    config["correct"] = ["opt0"]
    return config


def _order(config, seed):
    payload = PLUGIN.public_payload(config, "cs", {"shuffle_seed": seed} if seed else {})
    return [option["id"] for option in payload["options"]]


def test_seed_shuffles_options_repeatably():
    config = _many()
    assert _order(config, "seed-1") == _order(config, "seed-1")
    assert _order(config, "seed-1") != _order(config, "seed-2")
    assert sorted(_order(config, "seed-1")) == sorted(_order(config, None))


def test_no_seed_keeps_the_written_order():
    assert _order(_many(), None) == [f"opt{number}" for number in range(8)]


def test_yes_no_is_never_shuffled():
    config = yes_no()
    written = [option["id"] for option in config["options"]]
    for seed in ("a", "b", "c", "d", "e", "f"):
        assert _order(config, seed) == written


def test_shuffling_keeps_each_image_with_its_option():
    config = _many()
    config["options"][3]["image"] = {"asset": "x", "alt": {"cs": "Popis"}}
    payload = PLUGIN.public_payload(config, "cs", {"shuffle_seed": "seed-1"})
    with_image = [option["id"] for option in payload["options"] if option.get("image")]
    assert with_image == ["opt3"]


def test_none_of_the_answers_stays_last():
    drawn = PLUGIN.public_payload(_many(), "cs", {"shuffle_seed": "x", **ALL_QUESTIONS})
    payload = {**drawn, "id": "q"}
    html = PLUGIN.render_public(payload, "cs")
    assert html.rindex('value="opt') < html.index('value="none"')


def _solution(config, answer=None):
    return PLUGIN.render_solution(config, "cs", answer)


def test_solution_marks_correct_and_the_participants_wrong_answer():
    html = _solution(definition(), {"options": [B]})
    assert html.count("reveal-correct") == 1
    assert html.count("reveal-theirs") == 1


def test_trick_question_shows_none_of_the_answers_as_correct():
    html = _solution(definition(correct=()), None)
    with translation.override("en"):
        html = _solution(definition(correct=()), None)
    assert "None of the answers" in html
    assert html.count("reveal-correct") == 1


def test_none_ticked_on_a_normal_question_is_shown_as_theirs():
    with translation.override("en"):
        html = _solution(definition(), {"options": ["none"]})
    assert "None of the answers" in html
    assert "reveal-theirs" in html


def test_solution_shows_images_with_their_description():
    config = definition()
    config["options"][0]["image"] = {"asset": "a", "url": "/media/a", "alt": {"cs": "Popis"}}
    html = _solution(config)
    assert 'src="/media/a"' in html
    assert 'alt="Popis"' in html


def test_describe_definition_changes_with_the_source():
    with_source = definition((A,)) | {
        "image": {"asset": "x", "source": "https://a.example/1.png", "alt": {"cs": "P"}}
    }
    other = definition((A,)) | {
        "image": {"asset": "x", "source": "https://a.example/2.png", "alt": {"cs": "P"}}
    }
    assert PLUGIN.describe_definition(with_source, ["cs"]) != PLUGIN.describe_definition(
        other, ["cs"]
    )


def test_describe_definition_handles_an_image_with_no_copy():
    config = definition((A,)) | {
        "image": {"asset": None, "source": "https://a.example/1.png", "alt": {"cs": "P"}}
    }
    rows = PLUGIN.describe_definition(config, ["cs"])
    assert any("https://a.example/1.png" in row.value for row in rows)


def test_public_payload_hands_the_source_on_for_the_api_to_resolve():
    config = definition((A,)) | {
        "image": {"asset": None, "source": "https://a.example/1.png", "alt": {"cs": "P"}}
    }
    assert PLUGIN.public_payload(config, "cs")["image"]["source"] == "https://a.example/1.png"


def test_an_address_makes_an_image():
    form = {
        "prompt_cs": ["Q"],
        "option_0_cs": ["A"],
        "option_1_cs": ["B"],
        "correct_0": ["on"],
        "image_source": ["https://a.example/1.png"],
        "image_alt_cs": ["P"],
    }
    assert PLUGIN.parse_admin(form, ["cs"])["image"] == {
        "asset": None,
        "source": "https://a.example/1.png",
        "alt": {"cs": "P"},
    }


def csv_cells(**fields):
    return {"prompt_cs": "Q", "option_1_cs": "A", "option_2_cs": "B", "option_3_cs": "C"} | fields


def test_csv_letters_mark_correct_options():
    config = PLUGIN.from_csv(csv_cells(correct="A, c"), ["cs"])
    ids = [option["id"] for option in config["options"]]
    assert config["correct"] == [ids[0], ids[2]]
    assert config["allow_multiple"] is True


def test_csv_one_letter_means_one_answer_unless_said_otherwise():
    assert PLUGIN.from_csv(csv_cells(correct="B"), ["cs"])["allow_multiple"] is False
    config = PLUGIN.from_csv(csv_cells(correct="B", allow_multiple="true"), ["cs"])
    assert config["allow_multiple"] is True


def test_csv_letter_beyond_the_last_option_names_the_column():
    with pytest.raises(CsvRowError) as error:
        PLUGIN.from_csv(csv_cells(correct="D"), ["cs"])
    assert error.value.column == "correct"


def test_csv_numbers_refused():
    with pytest.raises(CsvRowError) as error:
        PLUGIN.from_csv(csv_cells(correct="1"), ["cs"])
    assert error.value.column == "correct"


def test_csv_six_options():
    cells = {"prompt_cs": "Q", "correct": "F"} | {f"option_{n}_cs": str(n) for n in range(1, 7)}
    config = PLUGIN.from_csv(cells, ["cs"])
    assert len(config["options"]) == 6
    assert config["correct"] == [config["options"][5]["id"]]
    assert PLUGIN.to_csv(config, ["cs"])["correct"] == "F"


def test_csv_yes_no():
    cells = csv_cells(kind="yes_no", correct="A", option_3_cs="")
    config = PLUGIN.from_csv(cells, ["cs"])
    assert config["kind"] == "yes_no"
    assert PLUGIN.to_csv(config, ["cs"])["kind"] == "yes_no"


def test_csv_images_in_question_and_option_keep_their_cells():
    cells = csv_cells(
        image="https://example.test/q.png",
        image_alt_cs="Popis",
        option_1_image="soubor.png",
        option_1_image_alt_cs="Volba",
    )
    config = PLUGIN.from_csv(cells, ["cs"])
    assert config["image"] == {
        "asset": None,
        "source": "https://example.test/q.png",
        "alt": {"cs": "Popis"},
    }
    assert config["options"][0]["image"]["source"] == "soubor.png"
    again = PLUGIN.to_csv(config, ["cs"])
    assert again["image"] == "https://example.test/q.png"
    assert again["option_1_image"] == "soubor.png"
    assert again["option_1_image_alt_cs"] == "Volba"


def test_csv_several_languages():
    cells = {
        "prompt_cs": "Otázka",
        "prompt_en": "Question",
        "option_1_cs": "A",
        "option_1_en": "A en",
        "option_2_cs": "B",
        "option_2_en": "B en",
        "correct": "A",
    }
    config = PLUGIN.from_csv(cells, ["cs", "en"])
    assert config["prompt"] == {"cs": "Otázka", "en": "Question"}
    assert config["options"][1]["text"] == {"cs": "B", "en": "B en"}
