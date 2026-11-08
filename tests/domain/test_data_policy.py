"""AC-77, AC-79: the data profile and the retention period are copied onto the run when it opens."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import authoring, data_policy, run_links, run_schedule, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def test_defaults_are_score_and_ninety_days():
    quiz = published_quiz()
    assert data_policy.rules_for_quiz(quiz) == {"profile": "score", "period": "90d"}


def test_open_copies_profile_and_period():
    quiz = published_quiz()
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    settings.set_override(settings.RETENTION_PERIOD, quiz, "1y", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert run.retention_json == {"profile": "answers", "period": "1y"}


def test_chosen_values_win_over_the_quiz():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, data={"profile": "none", "period": "30d"})
    assert data_policy.of(run) == {"profile": "none", "period": "30d"}


def test_quiz_change_after_open_does_not_touch_run():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override(settings.DATA_PROFILE, quiz, "detailed", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert data_policy.of(run)["profile"] == "score"


def test_plan_snapshots_and_update_replaces_while_planned():
    quiz = published_quiz()
    run = run_schedule.plan(
        quiz,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data={"profile": "answers"},
    )
    assert data_policy.of(run) == {"profile": "answers", "period": "90d"}
    run_schedule.update_plan(
        run,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data={"profile": "detailed", "period": "3y"},
    )
    run.refresh_from_db()
    assert data_policy.of(run) == {"profile": "detailed", "period": "3y"}


def test_open_run_profile_fixed():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.update_plan(
            run,
            starts_at=START,
            deadline_at=None,
            limit_sec=None,
            admin_id=ADMIN_ID,
            data={"profile": "detailed"},
        )
    run.refresh_from_db()
    assert data_policy.of(run)["profile"] == "score"


def test_missing_keys_use_defaults():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(retention_json={})
    run.refresh_from_db()
    assert data_policy.of(run) == {"profile": "score", "period": "90d"}


def test_test_run_follows_the_quiz_as_it_is_now():
    quiz = published_quiz()
    revision = authoring.latest_published(quiz)
    run = run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID).run
    settings.set_override(settings.DATA_PROFILE, quiz, "answers", admin_id=ADMIN_ID)
    assert data_policy.of(run)["profile"] == "answers"


def test_set_period_changes_it_on_open_and_ended_runs_and_audits_only_the_value():
    from app.kernel.models import AuditEvent

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    run_schedule.set_period(run, "1y", admin_id=ADMIN_ID)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.set_period(run, "permanent", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert data_policy.of(run) == {"profile": "score", "period": "permanent"}
    events = AuditEvent.objects.filter(action="run.period_changed")
    assert [event.details_json for event in events] == [{"period": "1y"}, {"period": "permanent"}]


def test_set_period_refuses_a_test_run_and_an_unknown_value():
    quiz = published_quiz()
    revision = authoring.latest_published(quiz)
    test_run = run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID).run
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.set_period(test_run, "1y", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.set_period(run, "forever", admin_id=ADMIN_ID)


@pytest.mark.parametrize(
    "frozen,expected",
    [
        ({"profile": "detailed"}, "detailed"),
        ({"store_answers": "all"}, "answers"),
        ({"store_answers": "images"}, "score"),
        ({}, "score"),
        (None, "score"),
    ],
)
def test_profile_of_attempt_upgrades_an_old_frozen_value(frozen, expected):
    assert data_policy.profile_of_attempt(Attempt(settings_json=frozen)) == expected


def test_what_each_profile_keeps():
    assert [data_policy.keeps_all_answers(p) for p in ("none", "score", "answers", "detailed")] == [
        False,
        False,
        True,
        True,
    ]
    assert [data_policy.keeps_duration(p) for p in ("none", "score", "answers", "detailed")] == [
        False,
        False,
        False,
        True,
    ]
