"""Applying a quiz type: its values become quiz overrides, the quiz remembers it.

AC-171, ADR-0062.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import cast

import pytest
from django.utils import timezone

from app.contracts import (
    ASK_NAME,
    ASK_WHEN,
    DUPLICATE_NAMES,
    OFFICIAL_ATTEMPT,
    REWARD_SOURCE,
    SCOREBOARD_VISIBILITY,
    WINNER_CONTACT,
    QuizTypePlugin,
)
from app.domain import authoring, quiz_types, run_schedule, setting_rules, settings
from app.domain.models import AppSetting
from app.domain.quiz_types import Change, TypeRefused, UnknownType
from app.domain.setting_rules import (
    AFTER_CLOSE_PROFILE,
    FLOW,
    RUN_BOARD,
    STATELESS,
    VISIBILITY,
)
from app.kernel import registry
from app.kernel.models import AuditEvent, PluginInstallation
from tests.domain.helpers import ADMIN_ID, make_quiz, published_quiz
from tests.support.photos import add_photo

pytestmark = pytest.mark.django_db
CONTEST_ONLY = [ASK_WHEN, DUPLICATE_NAMES, OFFICIAL_ATTEMPT, REWARD_SOURCE, WINNER_CONTACT]


def table(type_id):
    plugin = cast(QuizTypePlugin, registry.get("quiz_type", type_id))
    return dict(plugin.values())


def overrides(quiz):
    return dict(AppSetting.objects.filter(quiz=quiz).values_list("key", "value_json"))


def events(action):
    return AuditEvent.objects.filter(action=action)


def disable(module_id):
    PluginInstallation.objects.update_or_create(
        pk=module_id, defaults={"version": "1.0.0", "manifest_json": {}, "enabled": False}
    )


def apply(quiz, type_id):
    return quiz_types.apply(quiz, type_id, admin_id=ADMIN_ID)


def test_final_test_on_a_fresh_quiz_writes_its_table_and_remembers_the_type():
    quiz = make_quiz()
    apply(quiz, "final_test")
    assert overrides(quiz) == table("final_test")
    quiz.refresh_from_db()
    assert quiz.quiz_type == "final_test"
    applied = events("quiz.type_applied").get()
    assert applied.entity_type == "quiz" and applied.entity_id == str(quiz.id)
    assert applied.details_json == {"type": "final_test"}


def test_deviations_are_counted_against_the_type():
    quiz = make_quiz()
    apply(quiz, "final_test")
    assert quiz_types.deviations(quiz) == {}
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    assert quiz_types.deviations(quiz) == {settings.ATTEMPT_LIMIT: "30"}


def test_a_quiz_without_a_type_or_with_an_unknown_one_has_no_deviations():
    quiz = make_quiz()
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    assert quiz_types.deviations(quiz) == {}
    quiz.quiz_type = "gone"
    quiz.save()
    assert quiz_types.deviations(quiz) == {}


def test_changing_the_type_returns_the_old_types_own_keys_to_the_global_value():
    quiz = make_quiz()
    apply(quiz, "contest")
    shown = quiz_types.preview(quiz, "practice")
    removed = [change for change in shown.changes if change.new is None]
    assert sorted(change.key for change in removed) == sorted(CONTEST_ONLY)
    assert Change(REWARD_SOURCE, "quiz", None) in removed
    apply(quiz, "practice")
    assert overrides(quiz) == table("practice")


def test_listed_changes_are_only_values_that_differ():
    quiz = make_quiz()
    apply(quiz, "final_test")
    assert quiz_types.preview(quiz, "final_test").changes == []
    # Apply again is allowed and audited again.
    apply(quiz, "final_test")
    assert events("quiz.type_applied").count() == 2
    first = quiz_types.preview(make_quiz("jiny"), "final_test")
    assert Change(settings.ATTEMPT_LIMIT, "0", "30") in first.changes
    # The default already is "never": written as an override, not listed.
    assert settings.REVEAL_MOMENT not in [change.key for change in first.changes]


def test_a_clash_with_another_setting_is_adjusted():
    settings.set_global(settings.ANSWERS_VISIBILITY, "public", admin_id=ADMIN_ID)
    quiz = make_quiz()
    shown = quiz_types.preview(quiz, "practice")
    assert shown.adjusted == [Change(settings.ANSWERS_VISIBILITY, "public", "admins")]
    assert shown.refused == []
    apply(quiz, "practice")
    assert settings.quiz_override(settings.ANSWERS_VISIBILITY, quiz) == "admins"


def test_a_clash_with_an_open_run_refuses_the_type_and_writes_nothing():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    assert [clash.reason for clash in quiz_types.preview(quiz, "practice").refused] == [RUN_BOARD]
    with pytest.raises(TypeRefused) as refused:
        apply(quiz, "practice")
    assert [clash.reason for clash in refused.value.clashes] == [RUN_BOARD]
    assert overrides(quiz) == {}
    assert not events("quiz.type_applied").exists()
    quiz.refresh_from_db()
    assert quiz.quiz_type == ""


def test_a_refused_change_from_an_applied_type_keeps_the_old_type_and_its_values():
    quiz = published_quiz()
    apply(quiz, "pub_quiz")
    before = overrides(quiz)
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    with pytest.raises(TypeRefused):
        apply(quiz, "practice")
    quiz.refresh_from_db()
    assert quiz.quiz_type == "pub_quiz"
    assert overrides(quiz) == before


def test_applying_the_same_type_again_restores_a_deviation():
    quiz = make_quiz()
    apply(quiz, "final_test")
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    assert quiz_types.deviations(quiz) != {}
    apply(quiz, "final_test")
    assert overrides(quiz) == table("final_test")
    assert quiz_types.deviations(quiz) == {}


def test_keys_of_a_disabled_module_are_skipped():
    disable("rewards.threshold")
    quiz = make_quiz()
    assert quiz_types.preview(quiz, "contest").skipped == [REWARD_SOURCE, WINNER_CONTACT]
    apply(quiz, "contest")
    assert REWARD_SOURCE not in overrides(quiz) and WINNER_CONTACT not in overrides(quiz)
    assert quiz_types.deviations(quiz) == {}


def test_basic_removes_every_override_and_keeps_the_rest_of_the_quiz():
    quiz = make_quiz(anonymous_label={"cs": "Hráč NN"})
    settings.set_override(settings.GRADING_VIEW, quiz, "by_attempt", admin_id=ADMIN_ID)
    apply(quiz, "final_test")
    shown = quiz_types.preview(quiz, "basic")
    assert {change.key for change in shown.changes} == set(table("final_test")) | {
        settings.GRADING_VIEW
    }
    assert all(change.new is None for change in shown.changes)
    apply(quiz, "basic")
    assert overrides(quiz) == {}
    quiz.refresh_from_db()
    assert quiz.quiz_type == "basic" and quiz.anonymous_label == {"cs": "Hráč NN"}
    assert quiz_types.deviations(quiz) == {}
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    assert quiz_types.deviations(quiz) == {settings.ATTEMPT_LIMIT: None}


def test_basic_keeps_the_overrides_of_a_disabled_module():
    quiz = make_quiz()
    apply(quiz, "contest")
    disable("rewards.threshold")
    shown = quiz_types.preview(quiz, "basic")
    assert shown.skipped == [REWARD_SOURCE, WINNER_CONTACT]
    apply(quiz, "basic")
    assert overrides(quiz) == {REWARD_SOURCE: "quiz", WINNER_CONTACT: "require_email"}


def test_remove_forgets_the_type_and_keeps_every_value():
    quiz = make_quiz()
    quiz_types.remove(quiz, admin_id=ADMIN_ID)
    assert not events("quiz.type_removed").exists()
    apply(quiz, "final_test")
    quiz_types.remove(quiz, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.quiz_type == ""
    assert overrides(quiz) == table("final_test")
    assert events("quiz.type_removed").get().details_json == {"type": "final_test"}


def test_content_that_does_not_go_with_the_type_warns_and_the_type_still_applies():
    quiz = make_quiz()
    add_photo(quiz)
    assert quiz_types.preview(quiz, "practice").content == [settings.REVEAL_MOMENT]
    assert quiz_types.preview(quiz, "mock_test").content == []
    apply(quiz, "practice")
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) == "after_each"


def test_a_planned_run_is_a_live_run():
    quiz = published_quiz()
    assert quiz_types.preview(quiz, "final_test").live_run is False
    run_schedule.plan(
        quiz,
        starts_at=timezone.now() + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    assert quiz_types.preview(quiz, "final_test").live_run is True


def test_an_unknown_type_or_one_of_a_disabled_module_is_refused():
    quiz = make_quiz()
    with pytest.raises(UnknownType):
        quiz_types.preview(quiz, "gone")
    with pytest.raises(UnknownType):
        apply(quiz, "gone")
    disable("quiz_types.basic")
    with pytest.raises(UnknownType):
        apply(quiz, "practice")
    assert quiz_types.available() == []
    # The label of a remembered type is still there.
    remembered = quiz_types.get("practice")
    assert remembered is not None and remembered.id == "practice" and remembered.label()
    assert quiz_types.get("gone") is None


def test_available_types_are_in_their_order():
    assert [item.id for item in quiz_types.available()] == [
        "practice",
        "final_test",
        "resit_exam",
        "mock_test",
        "contest",
        "pub_quiz",
        "basic",
    ]


def test_apply_recomputes_from_the_current_state():
    quiz = make_quiz()
    assert quiz_types.preview(quiz, "practice").adjusted == []
    settings.set_global(settings.ANSWERS_VISIBILITY, "public", admin_id=ADMIN_ID)
    applied = apply(quiz, "practice")
    assert applied.adjusted == [Change(settings.ANSWERS_VISIBILITY, "public", "admins")]
    assert settings.quiz_override(settings.ANSWERS_VISIBILITY, quiz) == "admins"


def test_an_archived_quiz_cannot_take_a_type():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        apply(quiz, "practice")
    assert overrides(quiz) == {}


def test_basic_makes_no_adjustment_when_the_globals_clash():
    settings.set_global(settings.ANSWERS_VISIBILITY, "participant", admin_id=ADMIN_ID)
    settings.set_global(settings.DATA_PROFILE, "score", admin_id=ADMIN_ID)
    quiz = make_quiz()
    apply(quiz, "contest")
    shown = quiz_types.preview(quiz, "basic")
    assert shown.adjusted == []
    assert [clash.reason for clash in shown.refused] == [VISIBILITY]  # the globals' own clash


@dataclass(frozen=True)
class MadeUp:
    id: str = "made_up"
    version: str = "1.0.0"
    order: int = 99
    resets_all: bool = False

    def label(self) -> str:
        return "Made up"

    def description(self) -> str:
        return "Test only"

    def values(self):
        return {settings.ANSWERS_VISIBILITY: "participant", settings.DATA_PROFILE: "score"}


def test_adjustment_never_overwrites_the_types_own_key(monkeypatch):
    monkeypatch.setitem(registry._ports, ("quiz_type", "made_up"), (MadeUp(), "quiz_types.basic"))
    quiz = make_quiz()
    shown = quiz_types.preview(quiz, "made_up")
    assert [clash.reason for clash in shown.refused] == [VISIBILITY]  # refused, not adjusted
    assert shown.adjusted == []
    with pytest.raises(TypeRefused):
        apply(quiz, "made_up")
    assert overrides(quiz) == {}


@dataclass(frozen=True)
class AfterClose(MadeUp):
    id: str = "after_close_only"

    def values(self):
        return {settings.REVEAL_MOMENT: "after_close"}


def test_type_preview_score_admins_after_close(monkeypatch):
    """The type sets only the moment, so the profile and visibility are adjusted, not refused."""
    registry_key = ("quiz_type", "after_close_only")
    monkeypatch.setitem(registry._ports, registry_key, (AfterClose(), "quiz_types.basic"))
    quiz = make_quiz()
    shown = quiz_types.preview(quiz, "after_close_only")
    assert shown.refused == []
    assert {change.key: change.new for change in shown.adjusted} == {
        settings.DATA_PROFILE: "answers",
        settings.ANSWERS_VISIBILITY: "participant",
    }
    apply(quiz, "after_close_only")
    assert overrides(quiz) == {
        settings.REVEAL_MOMENT: "after_close",
        settings.DATA_PROFILE: "answers",
        settings.ANSWERS_VISIBILITY: "participant",
    }


def test_after_close_beside_a_profile_the_type_sets_itself_is_refused(monkeypatch):
    monkeypatch.setitem(registry._ports, ("quiz_type", "made_up"), (MadeUp(), "quiz_types.basic"))
    quiz = make_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_close", admin_id=ADMIN_ID)
    shown = quiz_types.preview(quiz, "made_up")
    assert AFTER_CLOSE_PROFILE in [clash.reason for clash in shown.refused]


def test_several_clashes_keep_rule_order():
    values = {
        settings.NAVIGATION_MODE: "pages",
        settings.REVEAL_MOMENT: "after_each",
        settings.DATA_PROFILE: "none",
        settings.ANSWERS_VISIBILITY: "public",
        ASK_NAME: "required",
        SCOREBOARD_VISIBILITY: "hidden",
    }
    found = setting_rules.clashes(values, None)
    assert [clash.reason for clash in found] == [FLOW, VISIBILITY, STATELESS]


def test_deviations_skip_a_disabled_module():
    quiz = make_quiz()
    apply(quiz, "contest")
    settings.set_override(REWARD_SOURCE, quiz, "none", admin_id=ADMIN_ID)
    assert REWARD_SOURCE in quiz_types.deviations(quiz)
    disable("rewards.threshold")
    assert REWARD_SOURCE not in quiz_types.deviations(quiz)


def test_resit_exam_preview_on_a_default_quiz_has_no_refused_clash():
    shown = quiz_types.preview(make_quiz("opravny"), "resit_exam")
    assert shown.refused == []
    assert Change(settings.REVEAL_MOMENT, "never", "after_close") in shown.changes
