"""AC-18: which quiz settings clash, one rule set for the settings forms and the quiz types."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from app.contracts import (
    ASK_EMAIL,
    ASK_NAME,
    REPEAT_ATTEMPTS,
    REWARD_SOURCE,
    SCOREBOARD_SECOND_SORT,
    SCOREBOARD_SHOW_DURATION,
    SCOREBOARD_VISIBILITY,
)
from app.domain import authoring, rewards, run_schedule, setting_rules, settings
from app.domain.setting_rules import (
    ADJUSTABLE,
    AFTER_CLOSE_PROFILE,
    AFTER_CLOSE_VISIBILITY,
    FLOW,
    NEEDS_TIMES,
    RESULT_AFTER_EACH,
    RESULT_STATELESS,
    RUN_BOARD,
    RUN_PROFILE,
    RUN_REWARDS,
    STATELESS,
    VISIBILITY,
    Clash,
    clashes,
)
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db

CONSISTENT = {
    settings.NAVIGATION_MODE: "step_back",
    settings.REVEAL_MOMENT: "never",
    settings.DATA_PROFILE: "score",
    settings.ANSWERS_VISIBILITY: "admins",
    REPEAT_ATTEMPTS: "allow",
    ASK_NAME: "off",
    ASK_EMAIL: "off",
    SCOREBOARD_VISIBILITY: "hidden",
    SCOREBOARD_SHOW_DURATION: "off",
    SCOREBOARD_SECOND_SORT: "submitted",
}
AFTER_EACH = {settings.REVEAL_MOMENT: "after_each"}


def reasons(changes, quiz=None):
    return [clash.reason for clash in clashes(CONSISTENT | changes, quiz)]


def test_consistent_values_do_not_clash():
    assert clashes(CONSISTENT, None) == []


def test_reasons_are_distinct():
    names = [
        FLOW,
        VISIBILITY,
        STATELESS,
        RESULT_STATELESS,
        RESULT_AFTER_EACH,
        NEEDS_TIMES,
        RUN_BOARD,
        RUN_REWARDS,
        AFTER_CLOSE_PROFILE,
        AFTER_CLOSE_VISIBILITY,
        RUN_PROFILE,
    ]
    assert len(set(names)) == len(names)


def test_pages_with_answers_after_each_is_flow():
    assert reasons({settings.NAVIGATION_MODE: "pages"} | AFTER_EACH) == [FLOW]
    assert clashes(CONSISTENT | {settings.NAVIGATION_MODE: "pages"} | AFTER_EACH, None) == [
        Clash(FLOW, settings.REVEAL_MOMENT)
    ]


def test_public_answers_under_score_is_visibility():
    assert clashes(CONSISTENT | {settings.ANSWERS_VISIBILITY: "public"}, None) == [
        Clash(VISIBILITY, settings.ANSWERS_VISIBILITY)
    ]


def test_required_name_under_nothing_is_stateless():
    found = clashes(CONSISTENT | {settings.DATA_PROFILE: "none", ASK_NAME: "required"}, None)
    assert found == [Clash(STATELESS, ASK_NAME, ASK_NAME)]


def test_visible_board_under_nothing_is_result_stateless():
    changes = {settings.DATA_PROFILE: "none", SCOREBOARD_VISIBILITY: "live"}
    assert clashes(CONSISTENT | changes, None) == [Clash(RESULT_STATELESS, SCOREBOARD_VISIBILITY)]


def test_live_board_with_answers_after_each_is_result_after_each():
    found = clashes(CONSISTENT | {SCOREBOARD_VISIBILITY: "live"} | AFTER_EACH, None)
    assert found == [Clash(RESULT_AFTER_EACH, settings.REVEAL_MOMENT)]


def test_duration_under_score_is_needs_times():
    found = clashes(CONSISTENT | {SCOREBOARD_SHOW_DURATION: "on"}, None)
    assert found == [Clash(NEEDS_TIMES, SCOREBOARD_VISIBILITY)]


def test_after_each_on_a_quiz_with_an_open_run_showing_a_board_is_run_board():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    assert clashes(CONSISTENT | AFTER_EACH, quiz) == [Clash(RUN_BOARD, settings.REVEAL_MOMENT)]
    # Global values count the runs of a quiz that takes the global answers setting.
    assert reasons(AFTER_EACH) == [RUN_BOARD]
    settings.set_override(settings.REVEAL_MOMENT, quiz, "never", admin_id=ADMIN_ID)
    assert reasons(AFTER_EACH) == []
    # Without answers after each question the run does not matter.
    assert reasons({}, quiz) == []


def test_run_board_is_not_repeated_beside_the_same_reason_in_the_values():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    assert reasons({SCOREBOARD_VISIBILITY: "live"} | AFTER_EACH, quiz) == [RESULT_AFTER_EACH]


def test_after_each_on_a_quiz_with_a_scheduled_run_with_rewards_is_run_rewards():
    quiz = published_quiz()
    rule = rewards.RuleData(
        kind="threshold",
        texts={"cs": {"name": "Odznak", "description": "", "claim": ""}},
        threshold_unit="percent",
        threshold_value=Decimal("80"),
    )
    rewards.save_rule(quiz, rule, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run_schedule.plan(
        quiz,
        starts_at=timezone.now() + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    assert reasons(AFTER_EACH, quiz) == [RUN_REWARDS]
    assert reasons(AFTER_EACH) == [RUN_REWARDS]


def test_a_missing_key_takes_the_global_value():
    settings.set_global(settings.NAVIGATION_MODE, "pages", admin_id=ADMIN_ID)
    values = {key: value for key, value in CONSISTENT.items() if key != settings.NAVIGATION_MODE}
    assert [c.reason for c in clashes(values | AFTER_EACH, None)] == [FLOW]
    # An empty field of a form means the global value too.
    assert reasons({settings.NAVIGATION_MODE: ""} | AFTER_EACH) == [FLOW]


def test_adjustable_values_end_their_clash():
    for reason, fix in ADJUSTABLE.items():
        for key, value in fix.items():
            assert value in settings.CATALOGUE[key].choices, (reason, key)
    public = {settings.ANSWERS_VISIBILITY: "public"}
    assert reasons(public) == [VISIBILITY]
    assert reasons(public | ADJUSTABLE[VISIBILITY]) == []
    duration = {SCOREBOARD_SHOW_DURATION: "on", SCOREBOARD_SECOND_SORT: "duration"}
    assert reasons(duration) == [NEEDS_TIMES]
    assert setting_rules.clashes(CONSISTENT | duration | ADJUSTABLE[NEEDS_TIMES], None) == []


AFTER_CLOSE = {settings.REVEAL_MOMENT: "after_close"}
ANSWERS = {settings.DATA_PROFILE: "answers", settings.ANSWERS_VISIBILITY: "participant"}


def test_after_close_with_score_profile_adjusts_profile():
    found = clashes(
        {**AFTER_CLOSE, settings.DATA_PROFILE: "score", settings.ANSWERS_VISIBILITY: "participant"},
        None,
    )
    assert [c.reason for c in found] == [AFTER_CLOSE_PROFILE]
    assert ADJUSTABLE[AFTER_CLOSE_PROFILE] == {settings.DATA_PROFILE: "answers"}


def test_after_close_with_score_profile_and_admins_reports_only_the_profile():
    assert reasons(AFTER_CLOSE) == [AFTER_CLOSE_PROFILE]


def test_after_close_with_none_profile_reports_the_profile():
    found = reasons(AFTER_CLOSE | {settings.DATA_PROFILE: "none"})
    assert AFTER_CLOSE_PROFILE in found and VISIBILITY not in found


def test_after_close_with_admins_visibility_adjusts_visibility():
    """AC-175: reveal after close with admins-only visibility adjusts the visibility."""
    found = clashes(CONSISTENT | AFTER_CLOSE | {settings.DATA_PROFILE: "answers"}, None)
    assert [c.reason for c in found] == [AFTER_CLOSE_VISIBILITY]
    assert ADJUSTABLE[AFTER_CLOSE_VISIBILITY] == {settings.ANSWERS_VISIBILITY: "participant"}


def test_after_close_with_answers_and_participant_visibility_is_fine():
    assert reasons(AFTER_CLOSE | ANSWERS) == []
    assert reasons(AFTER_CLOSE | ANSWERS | {settings.DATA_PROFILE: "detailed"}) == []


def test_after_close_on_a_quiz_with_a_live_score_run_is_run_profile():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)  # profile score by default
    found = clashes(CONSISTENT | AFTER_CLOSE | ANSWERS, quiz)
    assert [c.reason for c in found] == [RUN_PROFILE]
    assert found[0].key == settings.REVEAL_MOMENT
    assert RUN_PROFILE not in ADJUSTABLE
    # Without the moment the run does not matter.
    assert reasons(ANSWERS, quiz) == []


def test_live_run_with_answers_does_not_refuse_after_close():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, data={"profile": "answers"})
    assert reasons(AFTER_CLOSE | ANSWERS, quiz) == []
