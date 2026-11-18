"""Test add-ons: the limit of attempts and no more attempts after passing (contract 1.1)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import (
    AFTER_PASS,
    MAX_ATTEMPTS,
    PASS_MARK,
    REPEAT_ATTEMPTS,
    REVISION_MODE,
    UNFINISHED_ATTEMPT,
)
from app.domain import attempts, authoring, data_policy, participants, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def a_run(limit="2", **rules):
    rules = {REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: limit, UNFINISHED_ATTEMPT: "submitted"} | rules
    results = {PASS_MARK: rules.pop("mark", "0")}
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules, results=results)


def who(run, key="k"):
    return participants.find_or_create(run, key)


def finish(attempt, score, status=Attempt.Status.SUBMITTED):
    Attempt.objects.filter(pk=attempt.pk).update(
        status=status,
        submitted_at=T0,
        score=Decimal(score),
        max_score=Decimal(1),
    )


def test_a_limit_needs_a_participant():
    assert participants.needs_identity({REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: "2"})
    assert not participants.needs_identity({REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: "0"})


def test_abandoned_attempts_count():
    """AC-173: every started attempt counts toward the limit."""
    run = a_run("2")
    person = who(run)
    attempts.start(run, participant=person)  # first, left open
    attempts.start(run, participant=person)  # restart: the first is abandoned
    assert Attempt.objects.filter(status=Attempt.Status.ABANDONED).count() == 1
    with pytest.raises(attempts.AttemptError) as refused:
        attempts.start(run, participant=person)
    assert refused.value.code == "already_played"
    assert participants.attempts_left(run, person) == 0


def test_continue_resumes_even_at_the_limit():
    run = a_run("1", unfinished_attempt="continue")
    person = who(run)
    first = attempts.start(run, participant=person)
    again = attempts.start(run, participant=person)
    assert again.attempt.pk == first.attempt.pk


def test_limit_after_submissions():
    """AC-173: no attempt starts once the limit is used."""
    run = a_run("2")
    person = who(run)
    for _ in range(2):
        finish(attempts.start(run, participant=person).attempt, "0")
    with pytest.raises(attempts.AttemptError):
        attempts.start(run, participant=person)


def test_switched_chain_counts_once():
    run = a_run("2")
    person = who(run)
    first = attempts.start(run, participant=person).attempt
    second = Attempt.objects.create(run=run, participant=person, revision=run.current_revision)
    Attempt.objects.filter(pk=first.pk).update(status=Attempt.Status.SWITCHED, replaced_by=second)
    assert participants.attempts_left(run, person) == 1


def test_stop_after_passing():
    """AC-173: after_pass stop refuses another attempt once the kept score passed."""
    run = a_run("3", mark="50", after_pass="stop")
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "1")
    with pytest.raises(attempts.AttemptError) as refused:
        attempts.start(run, participant=person)
    assert refused.value.code == "already_played"


@pytest.mark.parametrize(("mode", "again"), [("percent", False), ("latest", True)])
def test_a_pass_on_an_older_revision_stops_only_where_the_mode_counts_it(mode, again):
    """AC-173; TD-047: "stop" reads the kept score, which under `latest` counts only the run's
    current revision, so after a switch a pass on an older revision no longer stops a new start
    (ADR-0053, addendum of 2026-11-17)."""
    quiz = published_quiz()
    run = authoring.open_run(
        quiz,
        admin_id=ADMIN_ID,
        rules={
            REPEAT_ATTEMPTS: "allow",
            MAX_ATTEMPTS: "3",
            UNFINISHED_ATTEMPT: "submitted",
            AFTER_PASS: "stop",
        },
        results={PASS_MARK: "50", REVISION_MODE: mode},
    )
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "1")
    add_question(quiz)
    newer = authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    run.refresh_from_db()
    if again:
        assert attempts.start(run, participant=person).attempt.revision_id == newer.id
    else:
        with pytest.raises(attempts.AttemptError) as refused:
            attempts.start(run, participant=person)
        assert refused.value.code == "already_played"


def test_more_after_passing_by_default():
    run = a_run("3", mark="50")
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "1")
    assert attempts.start(run, participant=person).attempt is not None


def test_failed_attempt_does_not_stop():
    run = a_run("3", mark="50", after_pass="stop")
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "0")
    attempts.start(run, participant=person)


def test_pending_grading_does_not_stop_after_pass():
    run = a_run("3", mark="50", after_pass="stop")
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "1", Attempt.Status.PENDING_GRADING)
    attempts.start(run, participant=person)


def test_no_limit_changes_nothing():
    run = a_run("0")
    person = who(run)
    for _ in range(3):
        finish(attempts.start(run, participant=person).attempt, "0")
    assert participants.attempts_left(run, person) is None


def test_forbid_is_unchanged_by_a_limit():
    run = a_run("5", repeat_attempts="forbid")
    person = who(run)
    finish(attempts.start(run, participant=person).attempt, "0")
    with pytest.raises(attempts.AttemptError):
        attempts.start(run, participant=person)


def test_test_run_ignores_the_limit():
    """AC-173: a test run ignores the limit and "no more attempts after passing"."""
    quiz = published_quiz()
    settings.set_override(MAX_ATTEMPTS, quiz, "1", admin_id=None)
    settings.set_override(AFTER_PASS, quiz, "stop", admin_id=None)
    fake = QuizRun(quiz=quiz, kind=QuizRun.Kind.TEST)
    rules = participants.rules_of(fake)
    assert rules[MAX_ATTEMPTS] == "0"
    assert rules[REPEAT_ATTEMPTS] == "allow"


def test_limit_with_profile_none_is_a_clash():
    """AC-173: a limit under the data profile none is a clash."""
    rules = {REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: "2"}
    found = data_policy.conflicts("none", rules, "admins", None)
    assert MAX_ATTEMPTS in found
    assert data_policy.conflicts("score", rules, "admins", None) == []
    assert data_policy.conflicts("none", rules | {MAX_ATTEMPTS: "0"}, "admins", None) == []


def test_stopping_after_a_pass_with_profile_none_is_a_clash():
    """AC-173: stopping after a pass needs a pass to remember, so it clashes with "none"."""
    rules = {REPEAT_ATTEMPTS: "allow", MAX_ATTEMPTS: "0", AFTER_PASS: "stop"}
    assert AFTER_PASS in data_policy.conflicts("none", rules, "admins", None)
    assert data_policy.conflicts("score", rules, "admins", None) == []
    assert data_policy.conflicts("none", rules | {AFTER_PASS: "more"}, "admins", None) == []


def test_attempts_left_counts_started_attempts():
    run = a_run("3")
    person = who(run)
    assert participants.attempts_left(run, person) == 3
    assert participants.attempts_left(run, None) == 3
    finish(attempts.start(run, participant=person).attempt, "0")
    assert participants.attempts_left(run, person) == 2
