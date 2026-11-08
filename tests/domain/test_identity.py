"""AC-73, AC-74: the name and e-mail of a participant, and who may hold a name."""

import threading
from datetime import UTC, datetime

import pytest
from django.db import connection

from app.domain import attempts, authoring, participants
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.busy import waiting
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)


def a_run(**rules):
    rules = {"ask_name": "required", "duplicate_names": "forbid"} | rules
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)


def send(run, name, key, *, automatic=False, email="", unfinished=None):
    who = participants.find_or_create(run, key)
    started = attempts.start(run, participant=who)
    rules = participants.rules_of(run)
    identity = participants.read_identity(rules, name, email, automatic=automatic)
    attempts.submit(
        started.attempt.id,
        started.token,
        {},
        "s" * 12 + key[:8] + str(Attempt.objects.count()),
        lenient=automatic,
        identity=identity,
    )
    return Participant.objects.get(pk=who.pk)


def code_of(call):
    with pytest.raises(attempts.AttemptError) as caught:
        call()
    return caught.value.code


def read(raw_name, raw_email="", automatic=False, **rules):
    return participants.read_identity(
        {"ask_name": "required", "ask_email": "off"} | rules,
        raw_name,
        raw_email,
        automatic=automatic,
    )


def test_name_is_collapsed_and_kept_as_typed():
    assert read("  Žába   Ok ").name == "Žába Ok"


def test_blank_name_counts_as_missing():
    assert code_of(lambda: read("   \t ")) == "name_required"


def test_optional_blank_name_is_empty():
    assert read(" ", ask_name="optional").name == ""


def test_name_is_ignored_when_not_asked():
    assert read("Karel", ask_name="off").name == ""


def test_name_longer_than_forty_is_refused():
    assert code_of(lambda: read("x" * 41)) == "name_too_long"


def test_invalid_email_refused():
    assert code_of(lambda: read("A", "nope", ask_email="optional")) == "email_invalid"


def test_required_email_missing_refused():
    assert code_of(lambda: read("A", "", ask_email="required")) == "email_required"


def test_email_is_kept_when_valid_and_none_when_not_asked():
    assert read("A", "a@b.cz", ask_email="optional").email == "a@b.cz"
    assert read("A", "a@b.cz", ask_email="off").email is None


def test_automatic_turns_every_problem_into_empty():
    identity = read("x" * 41, "nope", automatic=True, ask_email="required")
    assert (identity.name, identity.email) == ("", None)
    assert read("", automatic=True).name == ""


def test_duplicate_forbid_refuses_manual():
    run = a_run()
    send(run, "Žába  Ok", "a" * 20)
    who = participants.find_or_create(run, "b" * 20)
    started = attempts.start(run, participant=who)
    identity = participants.read_identity(
        participants.rules_of(run), "žába ok", "", automatic=False
    )
    code = code_of(
        lambda: attempts.submit(started.attempt.id, started.token, {}, "k" * 12, identity=identity)
    )
    assert code == "name_taken"
    assert Attempt.objects.get(pk=started.attempt.id).status == Attempt.Status.IN_PROGRESS
    assert Participant.objects.get(pk=who.pk).display_name == ""


def test_duplicate_allow_accepts():
    run = a_run(duplicate_names="allow")
    send(run, "Žába Ok", "a" * 20)
    second = send(run, "žába ok", "b" * 20)
    assert second.display_name == "žába ok"


def test_abandoned_attempt_holds_no_name():
    run = a_run(repeat_attempts="forbid", unfinished_attempt="submitted")
    who = participants.find_or_create(run, "a" * 20)
    attempts.start(run, participant=who)
    attempts.start(run, participant=who)  # abandons the first
    assert Participant.objects.get(pk=who.pk).display_name == ""
    assert send(run, "Jana", "b" * 20).display_name == "Jana"
    assert not participants.name_is_taken(run, "Karel")


def test_auto_submit_taken_name_drops_name():
    run = a_run()
    send(run, "Jana", "a" * 20)
    second = send(run, "jana", "b" * 20, automatic=True)
    assert second.display_name == ""
    assert Attempt.objects.filter(participant=second, status=Attempt.Status.SUBMITTED).count() == 1


def test_email_only_for_the_submitter():
    run = a_run(ask_email="optional")
    who = send(run, "Jana", "a" * 20, email="j@x.cz")
    assert who.email == "j@x.cz"
    assert who.name_key == "jana"


def test_missing_lists_asked_and_empty_fields():
    run = a_run(ask_email="required")
    who = send(run, "Jana", "a" * 20, automatic=True)
    assert participants.missing(who) == participants.Missing(name=False, email=True)
    assert not participants.missing(None)


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_name_one_wins():
    run = a_run()
    started = []
    for key in ("a" * 20, "b" * 20):
        who = participants.find_or_create(run, key)
        started.append(attempts.start(run, participant=who))
    identity = participants.read_identity(participants.rules_of(run), "Jana", "", automatic=False)
    outcomes = []

    def go(item, key):
        try:
            waiting(
                lambda: attempts.submit(
                    item.attempt.id, item.token, {}, key * 12, identity=identity
                )
            )
            outcomes.append("ok")
        except attempts.AttemptError as error:
            outcomes.append(error.code)
        finally:
            connection.close()

    pairs = zip(started, "ab", strict=True)
    threads = [threading.Thread(target=go, args=pair) for pair in pairs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["name_taken", "ok"]
    assert Participant.objects.filter(run=run, display_name="Jana").count() == 1


def test_later_blank_submission_keeps_earlier_name_and_email():
    run = a_run(
        ask_name="optional", ask_email="optional", duplicate_names="allow", repeat_attempts="allow"
    )
    send(run, "Jana", "a" * 20, email="j@x.cz")
    again = send(run, "", "a" * 20, automatic=True)
    assert (again.display_name, again.email, again.name_key) == ("Jana", "j@x.cz", "jana")


def test_taken_name_dropped_is_flagged_and_own_name_is_kept():
    run = a_run(ask_name="optional")
    send(run, "Jana", "a" * 20)
    dropped = send(run, "jana", "b" * 20, automatic=True)
    assert dropped.name_dropped
    assert not Participant.objects.get(display_name="Jana").name_dropped
    assert participants.missing(dropped).name


def test_optional_blank_is_not_missing():
    run = a_run(ask_name="optional", ask_email="optional")
    who = send(run, "", "a" * 20)
    assert not participants.missing(who)
