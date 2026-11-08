"""AC-86: every setting belongs to one named group and is basic or advanced."""

import pytest
from pydantic import ValidationError

from app.contracts import ADVANCED, BASIC, SETTING_GROUPS
from app.domain import settings
from app.kernel.manifest import SettingDeclaration


def test_groups_are_the_seven_in_order():
    assert SETTING_GROUPS == (
        "playing",
        "answers",
        "participants",
        "scoreboard",
        "data",
        "look",
        "technical",
    )


def test_every_setting_has_a_known_group_and_level():
    for key, definition in settings.CATALOGUE.items():
        assert definition.group in SETTING_GROUPS, key
        assert definition.level in (BASIC, ADVANCED), key


def test_basic_settings_are_exactly_the_first_cut():
    assert {k for k, d in settings.CATALOGUE.items() if d.level == BASIC} == {
        "navigation_mode",
        "page_size",
        "attempt_limit",
        "reveal_moment",
        "repeat_attempts",
        "ask_name",
        "scoreboard_visibility",
        "data_profile",
        "color_palette",
        "time_zone",
    }


@pytest.mark.parametrize(
    ("key", "group"),
    [
        ("navigation_mode", "playing"),
        ("shuffle_options", "playing"),
        ("unfinished_attempt", "playing"),
        ("local_resume", "playing"),
        ("photo_visibility", "answers"),
        ("none_option", "answers"),
        ("duplicate_names", "participants"),
        ("revision_mode", "scoreboard"),
        ("official_attempt", "scoreboard"),
        ("retention_period", "data"),
        ("announce_planned", "look"),
        ("color_palette", "look"),
        ("grading_view", "technical"),
        ("allow_internal_image_addresses", "technical"),
    ],
)
def test_group_of(key, group):
    assert settings.CATALOGUE[key].group == group


def _declaration(**extra):
    return SettingDeclaration(
        key="x", choices=["a"], default="a", label="X", value_labels={"a": "A"}, **extra
    )


def test_declaration_defaults_to_technical_and_advanced():
    declared = _declaration()
    assert (declared.group, declared.level) == ("technical", "advanced")


def test_manifest_refuses_an_unknown_group():
    with pytest.raises(ValidationError):
        _declaration(group="misc")


def test_manifest_refuses_an_unknown_level():
    with pytest.raises(ValidationError):
        _declaration(level="expert")
