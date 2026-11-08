"""A plan, a deadline and the limit a run takes (FR-10, FR-11, ADR-0048)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.db import OperationalError
from django.utils import timezone

from app.domain import authoring, quiz_state, run_schedule, settings
from app.domain.models import QuizRun
from app.kernel import events
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, open_quiz_run, published_quiz
from tests.support.clock import freeze
from tests.support.requirements import needs_reveal_at_end

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = NOW + timedelta(hours=1)
DEADLINE = NOW + timedelta(hours=2)


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def planned(quiz=None, starts_at=START, deadline_at=DEADLINE, limit_sec=None):
    quiz = quiz or published_quiz()
    return run_schedule.plan(
        quiz, starts_at=starts_at, deadline_at=deadline_at, limit_sec=limit_sec, admin_id=ADMIN_ID
    )


def stored(run):
    return QuizRun.objects.get(pk=run.pk)


def test_a_plan_waits_for_its_start():
    run = planned()
    run_schedule.settle(START - timedelta(seconds=1))
    assert stored(run).status == QuizRun.Status.SCHEDULED
    assert stored(run).opened_at is None


def test_a_plan_opens_on_the_first_request_after_its_start():
    run = planned()
    run_schedule.settle(START + timedelta(minutes=5))
    found = stored(run)
    assert found.status == QuizRun.Status.OPEN
    assert found.opened_at == START
    assert found.revision_rows.get().active_from == START
    assert AuditEvent.objects.filter(action="run.opened", entity_id=str(run.id)).count() == 1


def test_a_plan_takes_the_newest_published_revision():
    quiz = published_quiz()
    run = planned(quiz)
    add_question(quiz, prompt="Nová")
    newest = authoring.publish(quiz, admin_id=ADMIN_ID)
    assert stored(run).current_revision == newest
    run_schedule.settle(START)
    assert stored(run).current_revision == newest
    assert stored(run).revision_rows.get().revision == newest


def test_a_draft_never_reaches_a_plan():
    quiz = published_quiz()
    published = authoring.latest_published(quiz)
    run = planned(quiz)
    add_question(quiz, prompt="Koncept")
    run_schedule.settle(START)
    assert stored(run).current_revision == published


def reveal_after_each(quiz):
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    return quiz


def test_a_plan_stays_planned_when_requirements_are_unmet():
    quiz = reveal_after_each(published_quiz())
    run = planned(quiz)
    with needs_reveal_at_end():
        run_schedule.settle(START)
        assert stored(run).status == QuizRun.Status.SCHEDULED
    run_schedule.settle(START)
    assert stored(run).status == QuizRun.Status.OPEN


def test_the_deadline_closes_only_after_its_whole_second():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, deadline_at=DEADLINE)
    run_schedule.settle(DEADLINE + timedelta(milliseconds=900))
    assert stored(run).status == QuizRun.Status.OPEN
    run_schedule.settle(DEADLINE + timedelta(seconds=1))
    assert stored(run).status == QuizRun.Status.CLOSED
    assert stored(run).closed_at == DEADLINE


def test_reaching_the_deadline_emits_run_closed_once(monkeypatch):
    seen = []
    real = events.emit
    monkeypatch.setattr(events, "emit", lambda name, data: (seen.append(name), real(name, data))[1])
    authoring.open_run(published_quiz(), admin_id=ADMIN_ID, deadline_at=DEADLINE)
    seen.clear()
    later = DEADLINE + timedelta(seconds=1)
    run_schedule.settle(later)
    run_schedule.settle(later)
    assert seen == ["run.closed"]


def test_settle_twice_changes_nothing_more():
    run = planned()
    run_schedule.settle(START)
    run_schedule.settle(START + timedelta(minutes=1))
    assert stored(run).opened_at == START
    assert stored(run).revision_rows.count() == 1


def test_settle_writes_nothing_when_nothing_is_due(django_assert_num_queries):
    planned()
    with django_assert_num_queries(2):
        run_schedule.settle(NOW)


def test_settle_leaves_a_test_run_alone():
    quiz = published_quiz()
    run = QuizRun.all_kinds.create(
        quiz=quiz,
        kind=QuizRun.Kind.TEST,
        current_revision=authoring.latest_published(quiz),
        deadline_at=NOW - timedelta(days=1),
    )
    run_schedule.settle(NOW)
    assert QuizRun.all_kinds.get(pk=run.pk).status == QuizRun.Status.OPEN


@pytest.mark.parametrize(
    ("starts_at", "deadline_at", "code"),
    [
        (NOW, None, "start_in_past"),
        (NOW - timedelta(minutes=1), None, "start_in_past"),
        (START, START, "deadline_before_start"),
        (START, START - timedelta(minutes=1), "deadline_before_start"),
    ],
)
def test_a_plan_refuses_bad_times(starts_at, deadline_at, code):
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        planned(starts_at=starts_at, deadline_at=deadline_at)
    assert caught.value.code == code


def test_only_one_running_or_planned_run():
    quiz = published_quiz()
    planned(quiz)
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        planned(quiz)
    assert caught.value.code == "already_planned"
    with pytest.raises(authoring.RunAlreadyOpen):
        authoring.open_run(quiz, admin_id=ADMIN_ID)


def test_a_plan_is_refused_while_a_run_is_open():
    run = open_quiz_run()
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        planned(run.quiz)
    assert caught.value.code == "already_planned"


def test_a_plan_needs_something_published():
    with pytest.raises(authoring.NothingPublished):
        planned(make_quiz())


def test_a_plan_is_refused_with_unmet_requirements():
    quiz = reveal_after_each(published_quiz())
    with needs_reveal_at_end(), pytest.raises(authoring.RequirementUnmet):
        planned(quiz)


def test_update_plan_changes_the_plan():
    run = planned()
    later = START + timedelta(hours=1)
    run_schedule.update_plan(
        run, starts_at=later, deadline_at=None, limit_sec=300, admin_id=ADMIN_ID
    )
    found = stored(run)
    assert (found.starts_at, found.deadline_at, found.attempt_limit_sec) == (later, None, 300)


def test_update_plan_refuses_a_run_that_opened():
    run = open_quiz_run()
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        run_schedule.update_plan(
            run, starts_at=START, deadline_at=None, limit_sec=300, admin_id=ADMIN_ID
        )
    assert caught.value.code == "not_planned"


def test_cancel_frees_the_number():
    quiz = published_quiz()
    first = planned(quiz)
    assert first.run_no == 1
    run_schedule.cancel_plan(first, admin_id=ADMIN_ID)
    assert not QuizRun.objects.filter(pk=first.pk).exists()
    assert planned(quiz).run_no == 1


def test_cancel_refuses_a_run_that_opened():
    with pytest.raises(run_schedule.ScheduleRefused):
        run_schedule.cancel_plan(open_quiz_run(), admin_id=ADMIN_ID)


def test_start_now_opens_at_once_and_keeps_the_plans_deadline_and_limit():
    run = planned(limit_sec=600)
    run_schedule.start_now(run, admin_id=ADMIN_ID)
    found = stored(run)
    assert found.status == QuizRun.Status.OPEN
    assert found.opened_at == NOW
    assert found.deadline_at == DEADLINE
    assert found.attempt_limit_sec == 600


def test_open_now_refuses_a_past_deadline():
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        run_schedule.open_now(published_quiz(), deadline_at=NOW, limit_sec=None, admin_id=ADMIN_ID)
    assert caught.value.code == "deadline_before_start"


def test_open_run_copies_the_inherited_limit():
    settings.set_global(settings.ATTEMPT_LIMIT, "20", admin_id=None)
    quiz = published_quiz()
    assert settings.attempt_limit_seconds(quiz) == 1200
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "15", admin_id=None)
    assert authoring.open_run(quiz, admin_id=ADMIN_ID).attempt_limit_sec == 900


def test_a_quiz_can_drop_a_global_limit():
    settings.set_global(settings.ATTEMPT_LIMIT, "20", admin_id=None)
    quiz = published_quiz()
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "0", admin_id=None)
    assert authoring.open_run(quiz, admin_id=ADMIN_ID).attempt_limit_sec is None


def test_no_limit_by_default_and_none_on_a_question():
    assert settings.attempt_limit_seconds(published_quiz()) is None
    assert settings.ATTEMPT_LIMIT in settings.keys_for("quiz")
    assert settings.ATTEMPT_LIMIT not in settings.keys_for("question")


def test_a_limit_over_a_day_is_refused():
    with pytest.raises(settings.InvalidSettingValue):
        settings.set_global(settings.ATTEMPT_LIMIT, "1441", admin_id=None)


def test_a_quiz_with_a_plan_cannot_be_archived():
    run = planned()
    with pytest.raises(authoring.RunStillOpen):
        authoring.archive_quiz(run.quiz, admin_id=ADMIN_ID)


def test_set_deadline_refuses_less_than_a_minute_ahead():
    run = open_quiz_run()
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        run_schedule.set_deadline(run, NOW + timedelta(seconds=59), admin_id=ADMIN_ID)
    assert caught.value.code == "deadline_too_soon"
    run_schedule.set_deadline(run, NOW + timedelta(seconds=60), admin_id=ADMIN_ID)
    assert stored(run).deadline_at == NOW + timedelta(seconds=60)


def test_set_deadline_refuses_an_ended_run():
    run = open_quiz_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    with pytest.raises(run_schedule.ScheduleRefused) as caught:
        run_schedule.set_deadline(run, DEADLINE, admin_id=ADMIN_ID)
    assert caught.value.code == "not_open"


def test_set_deadline_none_removes_it_and_is_audited():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, deadline_at=DEADLINE)
    run_schedule.set_deadline(run, None, admin_id=ADMIN_ID)
    assert stored(run).deadline_at is None
    entry = AuditEvent.objects.get(action="run.deadline_changed")
    assert entry.details_json == {"from": DEADLINE.isoformat(), "to": None}


def test_a_planned_run_does_not_count_as_the_last_run():
    run = planned()
    state = quiz_state.of(run.quiz)
    assert state.last_run is None
    assert state.planned_run == run
    assert state.open_run is None
    assert state.main == quiz_state.MainAction.START_NOW
    assert state.secondary == (
        quiz_state.SecondaryAction.EDIT_PLAN,
        quiz_state.SecondaryAction.CANCEL_PLAN,
    )


def test_a_plan_with_unpublished_changes_offers_publishing_first():
    quiz = published_quiz()
    planned(quiz)
    add_question(quiz, prompt="Nová")
    state = quiz_state.of(quiz)
    assert state.main == quiz_state.MainAction.PUBLISH_CHANGES
    assert quiz_state.SecondaryAction.START_NOW in state.secondary
    assert quiz_state.SecondaryAction.CANCEL_PLAN in state.secondary


def test_a_request_settles_the_schedule(client, monkeypatch):
    run = planned()
    freeze(monkeypatch, START)
    assert client.get("/").status_code == 200
    assert stored(run).status == QuizRun.Status.OPEN


def test_a_failing_settle_does_not_fail_the_page(client, monkeypatch):
    def broken(now=None):
        raise OperationalError("database is locked")

    monkeypatch.setattr(run_schedule, "settle", broken)
    assert client.get("/").status_code == 200


def test_a_health_check_does_not_settle(client, monkeypatch):
    called = []
    monkeypatch.setattr(run_schedule, "settle", lambda now=None: called.append(now))
    client.get("/healthz")
    assert called == []


def test_opened_at_of_a_normal_start_is_now():
    assert open_quiz_run().opened_at == timezone.now()
