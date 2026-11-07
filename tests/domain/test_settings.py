import pytest

from app.domain import settings
from app.domain.models import AppSetting
from app.kernel.errors import StartupError
from app.kernel.manifest import Manifest
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, make_quiz

pytestmark = pytest.mark.django_db
KEY = settings.REVISION_SWITCH_POLICY


def test_default_when_nothing_is_set():
    assert settings.resolve(KEY) == "ask"


def test_global_value_beats_default():
    settings.set_global(KEY, "let_finish", admin_id=ADMIN_ID)
    assert settings.resolve(KEY) == "let_finish"
    assert settings.resolve(KEY, make_quiz()) == "let_finish"


def test_global_value_can_be_changed():
    settings.set_global(KEY, "let_finish", admin_id=ADMIN_ID)
    settings.set_global(KEY, "notify_switch", admin_id=ADMIN_ID)
    assert settings.resolve(KEY) == "notify_switch"
    assert AppSetting.objects.count() == 1


def test_quiz_override_beats_global():
    quiz, other = make_quiz("a"), make_quiz("b")
    settings.set_global(KEY, "let_finish", admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, "notify_switch", admin_id=ADMIN_ID)
    assert settings.resolve(KEY, quiz) == "notify_switch"
    assert settings.quiz_override(KEY, quiz) == "notify_switch"
    assert settings.resolve(KEY, other) == "let_finish"
    assert settings.quiz_override(KEY, other) is None


def test_deleting_override_returns_to_global():
    quiz = make_quiz()
    settings.set_global(KEY, "let_finish", admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, "notify_switch", admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, None, admin_id=ADMIN_ID)
    assert settings.resolve(KEY, quiz) == "let_finish"
    assert settings.quiz_override(KEY, quiz) is None


def test_unknown_key_is_refused():
    with pytest.raises(settings.UnknownSetting):
        settings.resolve("nope")
    with pytest.raises(settings.UnknownSetting):
        settings.set_global("nope", "ask", admin_id=ADMIN_ID)


def test_invalid_value_is_refused():
    with pytest.raises(settings.InvalidSettingValue):
        settings.set_global(KEY, "nope", admin_id=ADMIN_ID)
    with pytest.raises(settings.InvalidSettingValue):
        settings.set_override(KEY, make_quiz(), "nope", admin_id=ADMIN_ID)
    assert not AppSetting.objects.exists()


def test_change_is_audited():
    quiz = make_quiz()
    settings.set_global(KEY, "let_finish", admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, "notify_switch", admin_id=ADMIN_ID)
    settings.set_override(KEY, quiz, None, admin_id=ADMIN_ID)
    events = AuditEvent.objects.filter(action="setting.changed").order_by("created_at", "id")
    assert [event.details_json["value"] for event in events] == [
        "let_finish",
        "notify_switch",
        None,
    ]
    assert {event.details_json["key"] for event in events} == {KEY}


def test_palette_defaults_to_blue_teal():
    assert settings.resolve(settings.COLOR_PALETTE) == "blue_teal"


def test_palette_override_beats_global():
    quiz = make_quiz()
    settings.set_global(settings.COLOR_PALETTE, "red_plum", admin_id=None)
    settings.set_override(settings.COLOR_PALETTE, quiz, "indigo_pink", admin_id=None)
    assert settings.resolve(settings.COLOR_PALETTE, quiz) == "indigo_pink"
    assert settings.resolve(settings.COLOR_PALETTE) == "red_plum"


def test_unknown_palette_is_refused():
    with pytest.raises(settings.InvalidSettingValue):
        settings.set_global(settings.COLOR_PALETTE, "neon", admin_id=None)


def test_stored_value_no_longer_offered_falls_back_to_the_default():
    quiz = make_quiz()
    AppSetting.objects.create(key=settings.COLOR_PALETTE, quiz=None, value_json="retired")
    AppSetting.objects.create(key=settings.COLOR_PALETTE, quiz=quiz, value_json="retired")
    assert settings.resolve(settings.COLOR_PALETTE, quiz) == "blue_teal"
    assert settings.quiz_override(settings.COLOR_PALETTE, quiz) is None


def module_declaring(key):
    return Manifest.model_validate(
        {
            "id": "mod.a",
            "kind": "plugin",
            "version": "1.0.0",
            "app": "x.y",
            "api_compatibility": ">=1.0",
            "settings": [
                {
                    "key": key,
                    "choices": ["a"],
                    "default": "a",
                    "label": "A",
                    "value_labels": {"a": "A"},
                }
            ],
        }
    )


def test_a_duplicate_key_stops_the_start():
    with pytest.raises(StartupError):
        settings.register_modules([module_declaring(settings.COLOR_PALETTE)])


def test_a_module_setting_joins_the_catalogue(monkeypatch):
    monkeypatch.setattr(settings, "CATALOGUE", dict(settings.CATALOGUE))
    settings.register_modules([module_declaring("mod_setting")])
    assert settings.resolve("mod_setting") == "a"
    assert "mod_setting" in settings.keys_for("question")


def test_keys_for_follow_the_scopes():
    assert settings.NAVIGATION_MODE in settings.keys_for("quiz")
    assert settings.NAVIGATION_MODE not in settings.keys_for("question")
    assert settings.SHOW_SOURCES in settings.keys_for("question")


def test_question_beats_quiz_beats_global():
    quiz = make_quiz()
    question = {"settings": {"points": 1}}
    settings.set_global(settings.SHOW_SOURCES, "off", admin_id=ADMIN_ID)
    assert settings.resolve(settings.SHOW_SOURCES, quiz, question) == "off"
    settings.set_override(settings.SHOW_SOURCES, quiz, "on", admin_id=ADMIN_ID)
    assert settings.resolve(settings.SHOW_SOURCES, quiz, question) == "on"
    question["settings"][settings.SHOW_SOURCES] = "off"
    assert settings.resolve(settings.SHOW_SOURCES, quiz, question) == "off"


def test_a_question_value_no_longer_offered_is_skipped():
    quiz = make_quiz()
    settings.set_override(settings.SHOW_SOURCES, quiz, "off", admin_id=ADMIN_ID)
    question = {"settings": {settings.SHOW_SOURCES: "gone"}}
    assert settings.resolve(settings.SHOW_SOURCES, quiz, question) == "off"


def test_a_question_without_settings_follows_the_chain():
    assert settings.resolve(settings.SHOW_SOURCES, None, {}) == "on"
