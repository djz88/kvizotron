"""AC-76: the rules about participants are copied onto the run and fixed once it opens."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import authoring, participants, run_links, run_schedule, settings
from app.domain.models import QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def test_open_copies_rules_from_quiz():
    quiz = published_quiz()
    settings.set_override("repeat_attempts", quiz, "forbid", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert run.participant_rules_json["repeat_attempts"] == "forbid"
    assert set(run.participant_rules_json) == set(participants.PARTICIPANT_KEYS)


def test_quiz_change_after_open_does_not_touch_run():
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    settings.set_override("ask_name", quiz, "required", admin_id=None)
    run.refresh_from_db()
    assert participants.rules_of(run)["ask_name"] == "off"


def test_explicit_rules_override_the_quiz_and_missing_keys_use_defaults():
    quiz = published_quiz()
    settings.set_override("ask_email", quiz, "required", admin_id=None)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, rules={"ask_name": "optional"})
    rules = participants.rules_of(run)
    assert rules["ask_name"] == "optional"
    assert rules["ask_email"] == "required"
    old = QuizRun.objects.filter(pk=run.pk)
    old.update(participant_rules_json={})
    run.refresh_from_db()
    assert participants.rules_of(run) == {
        key: settings.CATALOGUE[key].default for key in participants.PARTICIPANT_KEYS
    }


def test_plan_snapshots_and_update_replaces_while_planned():
    quiz = published_quiz()
    run = run_schedule.plan(
        quiz,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        rules={"ask_name": "required"},
    )
    assert run.participant_rules_json["ask_name"] == "required"
    run_schedule.update_plan(
        run,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        rules={"repeat_attempts": "forbid"},
    )
    run.refresh_from_db()
    assert run.participant_rules_json["repeat_attempts"] == "forbid"
    assert run.participant_rules_json["ask_name"] == "off"


def test_open_run_rules_cannot_change():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.update_plan(
            run,
            starts_at=START,
            deadline_at=None,
            limit_sec=None,
            admin_id=ADMIN_ID,
            rules={"ask_name": "required"},
        )
    run.refresh_from_db()
    assert run.participant_rules_json["ask_name"] == "off"


def test_planned_run_keeps_its_snapshot_when_it_opens():
    quiz = published_quiz()
    run = run_schedule.plan(
        quiz,
        starts_at=START,
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        rules={"ask_email": "optional"},
    )
    settings.set_override("ask_email", quiz, "required", admin_id=None)
    run_schedule.start_now(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.OPEN
    assert participants.rules_of(run)["ask_email"] == "optional"


def test_test_run_reads_quiz_rules_and_allows_repeat():
    quiz = published_quiz()
    link = run_links.create(quiz, None, expires_at=None, admin_id=ADMIN_ID)
    settings.set_override("repeat_attempts", quiz, "forbid", admin_id=None)
    settings.set_override("ask_name", quiz, "required", admin_id=None)
    rules = participants.rules_of(link.run)
    assert rules["repeat_attempts"] == "allow"
    assert rules["ask_name"] == "required"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, False),
        ({"repeat_attempts": "forbid"}, True),
        ({"ask_name": "optional"}, True),
        ({"ask_email": "required"}, True),
    ],
)
def test_needs_identity(changes, expected):
    rules = {key: settings.CATALOGUE[key].default for key in participants.PARTICIPANT_KEYS}
    assert participants.needs_identity(rules | changes) is expected
