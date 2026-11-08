"""AC-09, AC-78: under the data profile "none" no result stays after a submission."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from app.domain import attempts, authoring, data_policy, run_schedule, settings
from app.domain.models import Attempt, AttemptAnswer, Participant, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, make_quiz, published_quiz
from tests.support.busy import waiting
from tests.support.clock import freeze
from tests.support.photos import add_photo

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
KEY = "k" * 20
SWITCH = authoring.Decision.NOTIFY_SWITCH
NONE = {"profile": "none"}


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)


def stateless_run(questions=1, **fields):
    quiz = published_quiz(questions=questions, **fields)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, data=NONE)


def answers_of(started):
    first = attempts.questions_of(started.attempt)[0]["id"]
    return {first: {"options": [OPTION_A]}}


def send(started, key=KEY):
    return attempts.submit(started.attempt.id, started.token, answers_of(started), key)


def code_of(call):
    with pytest.raises(attempts.AttemptError) as caught:
        call()
    return caught.value.code


def test_stateless_submit_leaves_no_rows():
    run = stateless_run()
    result = send(attempts.start(run))
    assert result.earned_points == 1
    assert not Attempt.objects.exists()
    assert not AttemptAnswer.objects.exists()
    assert not Participant.objects.exists()
    run.refresh_from_db()
    assert run.stateless_submitted == 1


def test_repeated_stateless_submit_is_gone():
    started = attempts.start(stateless_run())
    send(started)
    assert code_of(lambda: send(started)) == "attempt_gone"
    started.attempt.run.refresh_from_db()
    assert started.attempt.run.stateless_submitted == 1


@pytest.mark.parametrize("call", ["check", "remaining", "switch"])
def test_other_token_calls_find_the_attempt_gone(call):
    started = attempts.start(stateless_run())
    send(started)
    attempt_id, token = started.attempt.id, started.token
    calls = {
        "check": lambda: attempts.check(attempt_id, token, "x"),
        "remaining": lambda: attempts.remaining(attempt_id, token),
        "switch": lambda: attempts.switch(attempt_id, token, {}),
    }
    assert code_of(calls[call]) == "attempt_gone"


def test_a_forged_token_is_not_gone_but_invalid():
    started = attempts.start(stateless_run())
    send(started)
    assert code_of(lambda: attempts.remaining(started.attempt.id, "x")) == "invalid_token"


def test_a_gone_attempt_on_a_stored_profile_stays_not_found():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.id).delete()
    assert code_of(lambda: send(started)) == "not_found"


def test_racing_auto_and_manual_stateless_submit_counts_once():
    run = stateless_run()
    started = attempts.start(run)
    outcomes = []

    def go(key):
        try:
            outcomes.append(
                waiting(
                    lambda: attempts.submit(
                        started.attempt.id, started.token, answers_of(started), key
                    )
                )
            )
        except attempts.AttemptError as error:
            outcomes.append(error.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=go, args=(f"{n}" * 20,)) for n in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(map(str, outcomes)).count("attempt_gone") == 1
    assert sum(isinstance(item, attempts.AttemptResult) for item in outcomes) == 1
    run.refresh_from_db()
    assert run.stateless_submitted == 1
    assert not Attempt.objects.exists()


test_racing_auto_and_manual_stateless_submit_counts_once = pytest.mark.django_db(transaction=True)(
    test_racing_auto_and_manual_stateless_submit_counts_once
)


def test_switched_stateless_attempt_deletes_chain():
    run = stateless_run()
    first = attempts.start(run)
    question_id = authoring.editable_questions(run.quiz)[0]["id"]
    add_question(run.quiz, question_id=question_id, prompt="Nová")
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=SWITCH)
    second = attempts.switch(first.attempt.id, first.token, {}).started
    third_revision = second.attempt
    assert Attempt.objects.filter(run=run).count() == 2
    assert third_revision.settings_json["profile"] == "none"
    send(second)
    assert not Attempt.objects.exists()
    run.refresh_from_db()
    assert run.stateless_submitted == 1


def test_unsubmitted_stateless_attempt_stays_anonymous():
    run = stateless_run()
    started = attempts.start(run)
    attempt = Attempt.objects.get(pk=started.attempt.id)
    assert attempt.participant_id is None
    assert attempt.status == Attempt.Status.IN_PROGRESS
    assert not AttemptAnswer.objects.exists()
    run.refresh_from_db()
    assert run.stateless_submitted == 0


def test_stateless_event_carries_ids_and_score_only(monkeypatch):
    from app.kernel import events

    seen = []
    real = events.emit

    def record(name, payload):
        seen.append((name, payload))
        real(name, payload)

    monkeypatch.setattr(events, "emit", record)
    run = stateless_run()
    send(attempts.start(run))
    (payload,) = [payload for name, payload in seen if name == "attempt.submitted"]
    assert set(payload) == {"run_id", "score", "max_score"}
    assert payload["run_id"] == str(run.id)


def rules_for(key):
    return {
        "repeat_attempts": {"repeat_attempts": "forbid"},
        "ask_name": {"ask_name": "optional"},
        "ask_email": {"ask_email": "required"},
    }[key]


@pytest.mark.parametrize("key", ["repeat_attempts", "ask_name", "ask_email"])
def test_open_refuses_none_with_participant_rules(key):
    quiz = published_quiz()
    with pytest.raises(data_policy.StatelessConflict) as caught:
        authoring.open_run(quiz, admin_id=ADMIN_ID, data=NONE, rules=rules_for(key))
    assert caught.value.keys == [key]
    assert not QuizRun.objects.exists()


def test_open_refuses_none_with_visibility():
    quiz = published_quiz()
    settings.set_global(settings.DATA_PROFILE, "answers", admin_id=None)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=None)
    settings.set_global(settings.DATA_PROFILE, "score", admin_id=None)
    with pytest.raises(data_policy.StatelessConflict) as caught:
        authoring.open_run(quiz, admin_id=ADMIN_ID, data=NONE)
    assert caught.value.keys == ["answers_visibility"]


def test_open_refuses_none_with_photo_question():
    quiz = make_quiz()
    add_photo(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    with pytest.raises(data_policy.StatelessConflict) as caught:
        authoring.open_run(quiz, admin_id=ADMIN_ID, data=NONE)
    assert caught.value.keys == ["photo_question"]


def test_plan_and_update_plan_refuse_too():
    quiz = published_quiz()
    start = NOW + timedelta(hours=2)
    with pytest.raises(data_policy.StatelessConflict):
        run_schedule.plan(
            quiz,
            starts_at=start,
            deadline_at=None,
            limit_sec=None,
            admin_id=ADMIN_ID,
            data=NONE,
            rules={"ask_name": "required"},
        )
    run = run_schedule.plan(
        quiz, starts_at=start, deadline_at=None, limit_sec=None, admin_id=ADMIN_ID
    )
    with pytest.raises(data_policy.StatelessConflict):
        run_schedule.update_plan(
            run,
            starts_at=start,
            deadline_at=None,
            limit_sec=None,
            admin_id=ADMIN_ID,
            data=NONE,
            rules={"repeat_attempts": "forbid"},
        )


def test_conflicts_are_empty_for_other_profiles():
    rules = {"repeat_attempts": "forbid", "ask_name": "required", "ask_email": "required"}
    assert data_policy.conflicts("answers", rules, "participant", None) == []
    assert data_policy.conflicts("none", {}, "admins", None) == []


def test_planned_none_run_with_photo_revision_does_not_open():
    quiz = published_quiz()
    run = run_schedule.plan(
        quiz,
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data=NONE,
    )
    add_photo(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    # Publishing leaves it alone; here the revision is forced onto it.
    QuizRun.objects.filter(pk=run.pk).update(current_revision=authoring.latest_published(quiz))
    run_schedule.settle(NOW + timedelta(hours=2))
    run.refresh_from_db()
    assert run.status == QuizRun.Status.SCHEDULED
    event = AuditEvent.objects.get(action="run.open_refused")
    assert event.details_json == {"keys": ["photo_question"]}


def test_publish_keeps_revision_of_running_none_run_with_photo():
    run = stateless_run()
    before = run.current_revision_id
    add_photo(run.quiz)
    draft = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=SWITCH)
    run.refresh_from_db()
    assert run.current_revision_id == before != draft.id


def test_publish_keeps_revision_of_planned_none_run_with_photo():
    quiz = published_quiz()
    run = run_schedule.plan(
        quiz,
        starts_at=NOW + timedelta(hours=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
        data=NONE,
    )
    before = run.current_revision_id
    add_photo(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.current_revision_id == before


def test_publish_without_photo_still_moves_a_none_run():
    run = stateless_run()
    add_question(run.quiz, prompt="Další")
    draft = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=SWITCH)
    run.refresh_from_db()
    assert run.current_revision_id == draft.id


def test_held_back_notice_state():
    run = stateless_run()
    assert authoring.stateless_held_back(run.quiz) is False
    add_photo(run.quiz)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=SWITCH)
    assert authoring.stateless_held_back(run.quiz) is True


def link_for(quiz):
    from app.domain import run_links

    return run_links.create(quiz, None, expires_at=None, admin_id=ADMIN_ID)


def test_test_link_follows_live_none_and_leaves_no_row():
    quiz = make_quiz()
    add_question(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, "none", admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    link = link_for(quiz)
    started = attempts.start(link.run)
    assert started.attempt.settings_json["profile"] == "none"
    assert send(started).earned_points == 1
    assert not Attempt.objects.exists()
    link.run.refresh_from_db()
    assert link.run.stateless_submitted == 0
    assert code_of(lambda: send(started)) == "attempt_gone"


def test_test_link_with_photo_under_live_none_stores_as_score():
    quiz = make_quiz()
    add_photo(quiz)
    settings.set_override(settings.DATA_PROFILE, quiz, "none", admin_id=ADMIN_ID)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    started = attempts.start(link_for(quiz).run)
    assert started.attempt.settings_json["profile"] == "score"
    send(started)
    assert Attempt.objects.filter(pk=started.attempt.id, status=Attempt.Status.SUBMITTED).exists()
    Attempt.objects.filter(pk=started.attempt.id).delete()
    assert code_of(lambda: send(started)) == "not_found"
