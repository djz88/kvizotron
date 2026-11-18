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
from app.domain import authoring, rewards, run_flow, run_schedule, setting_rules, settings
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


def reasons(changes):
    return [clash.reason for clash in clashes(CONSISTENT | changes)]


def test_consistent_values_do_not_clash():
    assert clashes(CONSISTENT) == []


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
    assert clashes(CONSISTENT | {settings.NAVIGATION_MODE: "pages"} | AFTER_EACH) == [
        Clash(FLOW, settings.REVEAL_MOMENT)
    ]


def test_public_answers_under_score_is_visibility():
    assert clashes(CONSISTENT | {settings.ANSWERS_VISIBILITY: "public"}) == [
        Clash(VISIBILITY, settings.ANSWERS_VISIBILITY)
    ]


def test_required_name_under_nothing_is_stateless():
    found = clashes(CONSISTENT | {settings.DATA_PROFILE: "none", ASK_NAME: "required"})
    assert found == [Clash(STATELESS, ASK_NAME, ASK_NAME)]


def test_visible_board_under_nothing_is_result_stateless():
    changes = {settings.DATA_PROFILE: "none", SCOREBOARD_VISIBILITY: "live"}
    assert clashes(CONSISTENT | changes) == [Clash(RESULT_STATELESS, SCOREBOARD_VISIBILITY)]


def test_live_board_with_answers_after_each_is_result_after_each():
    found = clashes(CONSISTENT | {SCOREBOARD_VISIBILITY: "live"} | AFTER_EACH)
    assert found == [Clash(RESULT_AFTER_EACH, settings.REVEAL_MOMENT)]


def test_duration_under_score_is_needs_times():
    found = clashes(CONSISTENT | {SCOREBOARD_SHOW_DURATION: "on"})
    assert found == [Clash(NEEDS_TIMES, SCOREBOARD_VISIBILITY)]


def run_values(run, changes):
    return run_flow.of(run) | changes


def test_after_each_on_a_quiz_with_an_open_run_showing_a_board_is_run_board():
    """AC-18: the quiz and global values no longer judge a live run; `run_clashes` does."""
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    assert reasons(AFTER_EACH) == []
    found = setting_rules.run_clashes(run, run_values(run, AFTER_EACH))
    assert found == [Clash(RUN_BOARD, settings.REVEAL_MOMENT)]
    # Without answers after each question the run does not matter.
    assert setting_rules.run_clashes(run, run_values(run, {})) == []


def test_run_board_is_not_repeated_beside_the_same_reason_in_the_values():
    """AC-18: a board in the values is the quiz's own clash; the run adds nothing to the list."""
    assert reasons({SCOREBOARD_VISIBILITY: "live"} | AFTER_EACH) == [RESULT_AFTER_EACH]


def test_after_each_on_a_quiz_with_a_scheduled_run_with_rewards_is_run_rewards():
    """AC-18: reward rules of a planned run refuse answers after each question for that run."""
    quiz = published_quiz()
    rule = rewards.RuleData(
        kind="threshold",
        texts={"cs": {"name": "Odznak", "description": "", "claim": ""}},
        threshold_unit="percent",
        threshold_value=Decimal("80"),
    )
    rewards.save_rule(quiz, rule, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = run_schedule.plan(
        quiz,
        starts_at=timezone.now() + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    assert reasons(AFTER_EACH) == []
    found = setting_rules.run_clashes(run, run_values(run, AFTER_EACH))
    assert found == [Clash(RUN_REWARDS, settings.REVEAL_MOMENT)]


def test_a_missing_key_takes_the_global_value():
    settings.set_global(settings.NAVIGATION_MODE, "pages", admin_id=ADMIN_ID)
    values = {key: value for key, value in CONSISTENT.items() if key != settings.NAVIGATION_MODE}
    assert [c.reason for c in clashes(values | AFTER_EACH)] == [FLOW]
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
    assert setting_rules.clashes(CONSISTENT | duration | ADJUSTABLE[NEEDS_TIMES]) == []


AFTER_CLOSE = {settings.REVEAL_MOMENT: "after_close"}
ANSWERS = {settings.DATA_PROFILE: "answers", settings.ANSWERS_VISIBILITY: "participant"}


def test_after_close_with_score_profile_adjusts_profile():
    found = clashes(
        {**AFTER_CLOSE, settings.DATA_PROFILE: "score", settings.ANSWERS_VISIBILITY: "participant"}
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
    found = clashes(CONSISTENT | AFTER_CLOSE | {settings.DATA_PROFILE: "answers"})
    assert [c.reason for c in found] == [AFTER_CLOSE_VISIBILITY]
    assert ADJUSTABLE[AFTER_CLOSE_VISIBILITY] == {settings.ANSWERS_VISIBILITY: "participant"}


def test_after_close_with_answers_and_participant_visibility_is_fine():
    assert reasons(AFTER_CLOSE | ANSWERS) == []
    assert reasons(AFTER_CLOSE | ANSWERS | {settings.DATA_PROFILE: "detailed"}) == []


def test_after_close_on_a_quiz_with_a_live_score_run_is_run_profile():
    """AC-18: a live run that keeps no answers cannot take answers after the run closes."""
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)  # profile score by default
    assert clashes(CONSISTENT | AFTER_CLOSE | ANSWERS) == []
    found = setting_rules.run_clashes(run, run_values(run, AFTER_CLOSE))
    assert [c.reason for c in found] == [RUN_PROFILE]
    assert found[0].key == settings.REVEAL_MOMENT
    assert RUN_PROFILE not in ADJUSTABLE
    # Without the moment the run does not matter.
    assert setting_rules.run_clashes(run, run_values(run, {})) == []


def test_live_run_with_answers_does_not_refuse_after_close():
    """AC-18: a live run that keeps answers takes answers after the run closes."""
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, data={"profile": "answers"})
    assert setting_rules.run_clashes(run, run_values(run, AFTER_CLOSE)) == []
