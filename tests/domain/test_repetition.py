"""AC-70, AC-71: one browser, one participant per run, and what repeating means."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from django.db import connection

from app.domain import attempts, authoring, participants
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, OPTION_B, add_question, published_quiz
from tests.support.busy import waiting
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
KEY = "k" * 20


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)


def forbid_run(unfinished="continue", limit=None, questions=2):
    rules = {"repeat_attempts": "forbid", "unfinished_attempt": unfinished}
    return authoring.open_run(
        published_quiz(questions=questions), admin_id=ADMIN_ID, rules=rules, limit_sec=limit
    )


def person(run, key="a" * 20):
    return participants.find_or_create(run, key)


def send(started, key=KEY):
    return attempts.submit(started.attempt.id, started.token, {}, key)


def code_of(call):
    with pytest.raises(attempts.AttemptError) as caught:
        call()
    return caught.value.code


def test_hash_differs_between_runs_for_same_key():
    first, second = forbid_run(), authoring.open_run(published_quiz("jiny"), admin_id=ADMIN_ID)
    assert participants.key_hash(first, "same") != participants.key_hash(second, "same")
    assert "same" not in participants.key_hash(first, "same")


def test_find_or_create_is_one_row_per_key():
    run = forbid_run()
    assert person(run).pk == person(run).pk
    assert Participant.objects.count() == 1


def test_forbid_refuses_second_after_submit():
    run = forbid_run()
    who = person(run)
    send(attempts.start(run, participant=who))
    assert code_of(lambda: attempts.start(run, participant=who)) == "already_played"
    assert Attempt.objects.count() == 1


def test_allow_needs_no_participant():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    first = attempts.start(run)
    second = attempts.start(run)
    assert first.attempt.id != second.attempt.id
    assert first.attempt.participant is None


def test_continue_resumes_same_attempt():
    run = forbid_run()
    who = person(run)
    first = attempts.start(run, participant=who)
    again = attempts.start(run, participant=who)
    assert again.attempt.id == first.attempt.id
    assert again.attempt.selection_json == first.attempt.selection_json
    assert again.submission_key != first.submission_key
    send(again)
    assert Attempt.objects.get(pk=first.attempt.id).status == Attempt.Status.SUBMITTED


def test_continue_expired_is_time_up(monkeypatch):
    run = forbid_run(limit=600)
    who = person(run)
    attempts.start(run, participant=who)
    freeze(monkeypatch, NOW + timedelta(seconds=601))
    assert code_of(lambda: attempts.start(run, participant=who)) == "time_is_up"
    assert Attempt.objects.count() == 1


def test_used_refuses_after_start():
    run = forbid_run("used")
    who = person(run)
    attempts.start(run, participant=who)
    assert code_of(lambda: attempts.start(run, participant=who)) == "already_played"


def test_submitted_mode_abandons_previous():
    run = forbid_run("submitted")
    who = person(run)
    old = attempts.start(run, participant=who)
    new = attempts.start(run, participant=who)
    assert new.attempt.id != old.attempt.id
    assert Attempt.objects.get(pk=old.attempt.id).status == Attempt.Status.ABANDONED
    assert code_of(lambda: send(old, "o" * 20)) == "attempt_closed"
    send(new, "n" * 20)
    assert code_of(lambda: attempts.start(run, participant=who)) == "already_played"


def test_resume_follows_switch_chain():
    run = forbid_run()
    who = person(run)
    old = attempts.start(run, participant=who)
    first_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=first_id)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    run.refresh_from_db()
    moved = attempts.switch(old.attempt.id, old.token, {}).started
    assert moved.attempt.id != old.attempt.id
    assert Attempt.objects.get(pk=old.attempt.id).status == Attempt.Status.SWITCHED
    assert moved.attempt.participant_id == who.pk
    again = attempts.start(run, participant=who)
    assert again.attempt.id == moved.attempt.id
    assert again.attempt.status == Attempt.Status.IN_PROGRESS


def test_two_tabs_cannot_both_submit_under_forbid():
    run = forbid_run()
    who = person(run)
    first = attempts.start(run, participant=who)
    # Two attempts for one participant, as a race that passed both starts would leave.
    second = attempts.start(run)
    Attempt.objects.filter(pk=second.attempt.id).update(participant=who)
    send(first, "1" * 20)
    assert code_of(lambda: send(second, "2" * 20)) == "already_played"
    assert Attempt.objects.get(pk=second.attempt.id).status == Attempt.Status.IN_PROGRESS


@pytest.mark.django_db(transaction=True)
def test_concurrent_starts_make_one_attempt():
    run = forbid_run()
    who = person(run)
    outcomes = []

    def go():
        try:
            outcomes.append(waiting(lambda: attempts.start(run, participant=who)).attempt.id)
        except Exception as error:  # noqa: BLE001 - the outcome is what is checked
            outcomes.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert Attempt.objects.filter(run=run, status=Attempt.Status.IN_PROGRESS).count() == 1
    assert len(set(outcomes)) == 1


def abandoned_pair():
    run = forbid_run("submitted")
    who = person(run)
    old = attempts.start(run, participant=who)
    new = attempts.start(run, participant=who)
    return run, old, new


def test_abandoned_attempt_cannot_switch_after_a_new_revision():
    run, old, _new = abandoned_pair()
    first_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, OPTION_B, question_id=first_id)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.NOTIFY_SWITCH)
    assert code_of(lambda: attempts.switch(old.attempt.id, old.token, {})) == "attempt_closed"
    assert Attempt.objects.filter(run=run, status=Attempt.Status.IN_PROGRESS).count() == 1


def test_abandoned_attempt_is_refused_by_check_and_remaining():
    _run, old, _new = abandoned_pair()
    assert code_of(lambda: attempts.remaining(old.attempt.id, old.token)) == "attempt_closed"
    assert code_of(lambda: attempts.check(old.attempt.id, old.token, "q")) == "attempt_closed"
    assert code_of(lambda: attempts.verify_open(old.attempt.id, old.token)) == "attempt_closed"


@pytest.mark.parametrize("lenient", [False, True])
def test_abandon_between_check_and_store_is_attempt_closed(monkeypatch, lenient):
    run = forbid_run("submitted")
    who = person(run)
    old = attempts.start(run, participant=who)
    real = attempts._store

    def abandon_first(*args, **kwargs):
        Attempt.objects.filter(pk=old.attempt.id).update(status=Attempt.Status.ABANDONED)
        return real(*args, **kwargs)

    monkeypatch.setattr(attempts, "_store", abandon_first)
    with pytest.raises(attempts.AttemptError) as caught:
        attempts.submit(old.attempt.id, old.token, {}, KEY, lenient=lenient)
    assert caught.value.code == "attempt_closed"
