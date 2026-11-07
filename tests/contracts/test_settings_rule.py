"""Every setting faces the question where it fits: global, quiz, question (ADR-0042)."""

import pytest
from pydantic import ValidationError

from app.api.admin_forms import GlobalSettingsForm, QuestionCommonForm, QuizBehaviourForm
from app.domain import settings
from app.kernel import registry
from app.kernel.discovery import installed_modules
from app.kernel.manifest import Manifest
from tests.domain.helpers import make_quiz

BASE = {
    "id": "mod.a",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "x.y",
    "api_compatibility": ">=1.0",
}


def declaration(**fields):
    return {
        "key": "mod_setting",
        "choices": ["a", "b"],
        "default": "a",
        "label": "A setting",
        "value_labels": {"a": "A", "b": "B"},
    } | fields


def test_a_manifest_without_settings_is_refused():
    with pytest.raises(ValidationError):
        Manifest.model_validate(BASE)


def test_no_settings_is_stated_with_an_empty_list():
    assert Manifest.model_validate(BASE | {"settings": []}).settings == []


def test_the_default_scope_is_the_whole_chain():
    manifest = Manifest.model_validate(BASE | {"settings": [declaration()]})
    assert manifest.settings[0].scopes == ["global", "quiz", "question"]


def test_a_narrower_scope_needs_a_reason():
    with pytest.raises(ValidationError):
        Manifest.model_validate(BASE | {"settings": [declaration(scopes=["global"])]})


def test_a_narrower_scope_with_a_reason_is_accepted():
    narrow = declaration(scopes=["global"], scope_reason="It guards the server")
    assert Manifest.model_validate(BASE | {"settings": [narrow]}).settings[0].scopes == ["global"]


def test_an_unknown_scope_is_refused():
    with pytest.raises(ValidationError):
        unknown = declaration(scopes=["run"], scope_reason="x")
        Manifest.model_validate(BASE | {"settings": [unknown]})


def test_a_default_outside_the_choices_is_refused():
    with pytest.raises(ValidationError):
        Manifest.model_validate(BASE | {"settings": [declaration(default="c")]})


def test_a_choice_without_a_label_is_refused():
    with pytest.raises(ValidationError):
        Manifest.model_validate(BASE | {"settings": [declaration(value_labels={"a": "A"})]})


def test_every_installed_module_has_a_valid_manifest():
    assert all(isinstance(module.settings, list) for module in installed_modules())


def test_the_catalogue_follows_the_rule():
    for definition in settings.CATALOGUE.values():
        narrower = set(definition.scopes) != set(settings.ALL_SCOPES)
        assert not narrower or definition.scope_reason, definition.key
        assert set(definition.scopes) <= set(settings.ALL_SCOPES), definition.key
        assert set(definition.choices) == set(definition.value_labels), definition.key
        assert definition.label, definition.key


@pytest.mark.django_db
def test_each_scope_of_each_setting_is_offered_on_its_page():
    global_fields = GlobalSettingsForm().fields
    quiz_fields = QuizBehaviourForm(quiz=make_quiz()).fields
    question_fields = set()
    for key in registry.keys("question_type"):
        plugin = registry.get("question_type", key)
        form = QuestionCommonForm(plugin=plugin, strategies=[], locales=["cs"])
        question_fields |= set(form.fields)
    for key, definition in settings.CATALOGUE.items():
        assert ("global" in definition.scopes) == (key in global_fields), key
        assert ("quiz" in definition.scopes) == (key in quiz_fields), key
        assert ("question" in definition.scopes) == (f"setting_{key}" in question_fields), key
