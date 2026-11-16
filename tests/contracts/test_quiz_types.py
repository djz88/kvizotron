"""The seven quiz types of `quiz_types.basic` match the table of the design (ADR-0062)."""

import pytest
from django.utils import translation

from app.kernel import registry
from app.plugins.quiz_types.plugin import TYPES
from tests.contracts.quiz_type import QuizTypeContract

KEYS = ("practice", "final_test", "resit_exam", "mock_test", "contest", "pub_quiz", "basic")


def by_id(key: str):
    return next(plugin for plugin in TYPES if plugin.id == key)


class TestQuizTypes(QuizTypeContract):
    plugins = list(TYPES)


def test_seven_types_in_order():
    assert [plugin.id for plugin in sorted(TYPES, key=lambda p: p.order)] == list(KEYS)


@pytest.mark.django_db
def test_each_type_is_registered_by_the_module():
    assert set(registry.keys("quiz_type")) == set(KEYS)
    for key in KEYS:
        assert registry.get("quiz_type", key) is by_id(key)
        assert registry.owner_of("quiz_type", key) == "quiz_types.basic"


def test_only_basic_resets_all():
    assert [plugin.id for plugin in TYPES if plugin.resets_all] == ["basic"]


def test_labels():
    with translation.override("en"):
        labels = [by_id(key).label() for key in KEYS]
    assert labels == [
        "Practice",
        "Final test",
        "Exam with a resit",
        "Mock test",
        "Contest",
        "Pub quiz",
        "Basic quiz",
    ]


def test_labels_in_czech():
    with translation.override("cs"):
        assert [by_id(key).label() for key in KEYS] == [
            "Procvičování",
            "Závěrečný test",
            "Zkouška s opravným pokusem",
            "Zkouška nanečisto",
            "Soutěž o ceny",
            "Hospodský kvíz",
            "Jednoduchý kvíz",
        ]


def test_descriptions_say_what_the_type_leaves_to_the_admin():
    with translation.override("en"):
        contest, pub, basic = (by_id(k).description() for k in ("contest", "pub_quiz", "basic"))
    assert "Rewards tab" in contest
    assert "phone per team" in pub and "team name as nickname" in pub
    assert "global settings" in basic


def test_practice_values():
    assert by_id("practice").values() == {
        "navigation_mode": "step_no_back",
        "reveal_moment": "after_each",
        "reveal_level": "explanations",
        "shuffle_questions": "on",
        "shuffle_options": "on",
        "attempt_limit": "0",
        "repeat_attempts": "allow",
        "ask_name": "off",
        "ask_email": "off",
        "scoreboard_visibility": "hidden",
        "data_profile": "score",
        "show_sources": "on",
    }


def test_final_test_values():
    assert by_id("final_test").values() == {
        "navigation_mode": "step_no_back",
        "reveal_moment": "never",
        "shuffle_questions": "on",
        "shuffle_options": "on",
        "attempt_limit": "30",
        "repeat_attempts": "forbid",
        "ask_name": "required",
        "ask_when": "start",
        "ask_email": "off",
        "duplicate_names": "allow",
        "scoreboard_visibility": "hidden",
        "official_attempt": "first",
        "pass_mark": "70",
        "data_profile": "answers",
        "show_sources": "off",
    }


def test_resit_exam_values():
    assert by_id("resit_exam").values() == {
        "navigation_mode": "step_no_back",
        "shuffle_questions": "on",
        "shuffle_options": "on",
        "attempt_limit": "30",
        "repeat_attempts": "allow",
        "max_attempts": "2",
        "after_pass": "more",
        "ask_name": "required",
        "ask_when": "start",
        "ask_email": "off",
        "duplicate_names": "allow",
        "scoreboard_visibility": "hidden",
        "official_attempt": "best",
        "pass_mark": "70",
        "reveal_moment": "after_close",
        "reveal_level": "explanations",
        "data_profile": "answers",
        "answers_visibility": "participant",
        "show_sources": "off",
    }


def test_mock_test_values():
    assert by_id("mock_test").values() == {
        "navigation_mode": "step_back",
        "reveal_moment": "at_end",
        "reveal_level": "explanations",
        "shuffle_questions": "on",
        "shuffle_options": "on",
        "attempt_limit": "30",
        "repeat_attempts": "allow",
        "ask_name": "off",
        "ask_email": "off",
        "scoreboard_visibility": "hidden",
        "pass_mark": "70",
        "max_attempts": "0",
        "data_profile": "score",
        "show_sources": "on",
    }


def test_contest_values():
    assert by_id("contest").values() == {
        "navigation_mode": "step_back",
        "reveal_moment": "never",
        "shuffle_questions": "on",
        "shuffle_options": "on",
        "attempt_limit": "0",
        "repeat_attempts": "forbid",
        "ask_name": "required",
        "ask_when": "end",
        "ask_email": "required",
        "duplicate_names": "forbid",
        "scoreboard_visibility": "after_end",
        "official_attempt": "first",
        "reward_source": "quiz",
        "winner_contact": "require_email",
        "data_profile": "score",
        "show_sources": "off",
    }


def test_pub_quiz_values():
    assert by_id("pub_quiz").values() == {
        "navigation_mode": "pages",
        "page_size": "10",
        "reveal_moment": "at_end",
        "reveal_level": "answers",
        "shuffle_questions": "off",
        "shuffle_options": "off",
        "attempt_limit": "0",
        "repeat_attempts": "forbid",
        "ask_name": "required",
        "ask_when": "start",
        "ask_email": "off",
        "duplicate_names": "forbid",
        "scoreboard_visibility": "live",
        "official_attempt": "first",
        "data_profile": "score",
        "show_sources": "on",
    }


def test_basic_values():
    basic = by_id("basic")
    assert basic.resets_all
    assert basic.values() == {}
