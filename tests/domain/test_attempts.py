from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from unittest import mock
from uuid import UUID, uuid7

import pytest
from django.db import IntegrityError, OperationalError
from django.utils import timezone

from app.domain import attempts, authoring, settings, tokens
from app.domain.models import Attempt, QuizRevision
from app.kernel import registry
from app.kernel.models import PluginInstallation
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    add_question,
    definition,
    keep,
    make_quiz,
    open_quiz_run,
)

KEY = "key-00000001"


def answers_for(run, *options):
    questions = run.current_revision.snapshot_json["questions"]
    return {q["id"]: {"options": [o]} for q, o in zip(questions, options, strict=False)}


def submit(run, started, *options, key=KEY):
    return attempts.submit(started.attempt.id, started.token, answers_for(run, *options), key)


@pytest.fixture
def run(db):
    return open_quiz_run()


@pytest.fixture
def started(run):
    return attempts.start(run)


def test_start_on_closed_run_is_refused(run):
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    with pytest.raises(attempts.AttemptError) as error:
        attempts.start(run)
    assert error.value.code == "run_closed"
    assert not Attempt.objects.exists()


def test_start_pins_revision_and_token_lifetime(run):
    started = attempts.start(run)
    claims = tokens.verify(started.token)
    assert started.attempt.revision_id == run.current_revision_id
    assert claims.expires_at - claims.started_at == timedelta(hours=24)
    assert claims.manifest_hash == attempts.manifest_hash(
        [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    )


def test_submission_key_is_random_and_not_uuid(run):
    first, second = attempts.start(run), attempts.start(run)
    assert first.submission_key != second.submission_key
    assert len(first.submission_key) >= 16
    with pytest.raises(ValueError):
        UUID(first.submission_key)


def test_correct_answer_scores_full_points(run, started):
    Attempt.objects.update(settings_json={**started.attempt.settings_json, "profile": "detailed"})
    result = submit(run, started, OPTION_A)
    assert (result.earned_points, result.max_points) == (1, 1)
    assert (result.percentage, result.correct_count) == (100, 1)
    attempt = Attempt.objects.get()
    assert attempt.status == Attempt.Status.SUBMITTED
    assert (attempt.score, attempt.max_score, attempt.correct_count) == (1, 1, 1)
    assert attempt.submission_key == KEY
    assert attempt.duration_ms is not None


def test_wrong_answer_scores_zero(run, started):
    result = submit(run, started, OPTION_B)
    assert (result.earned_points, result.max_points, result.correct_count) == (0, 1, 0)


def test_blank_answer_scores_zero(run, started):
    result = attempts.submit(started.attempt.id, started.token, {}, KEY)
    assert (result.earned_points, result.max_points, result.correct_count) == (0, 1, 0)


@pytest.mark.django_db
def test_percentage_is_exact_before_rounding():
    """AC-10: five equal questions with 4 correct are 80 %, below a 90 % threshold."""
    run = open_quiz_run(questions=5)
    result = submit(run, attempts.start(run), OPTION_A, OPTION_A, OPTION_A, OPTION_A, OPTION_B)
    assert result.percentage == 80
    assert result.percentage < 90
    run = open_quiz_run("third", questions=3)
    result = submit(run, attempts.start(run), OPTION_A, OPTION_B, OPTION_B, key="key-00000002")
    assert result.percentage == Fraction(100, 3)
    assert result.percentage_display == 33.33


def test_attempt_stays_on_revision_after_new_publication(run, started):
    """AC-04: started on revision 1, published as revision 2: graded on 1, kept in its history."""
    quiz = run.quiz
    first = run.current_revision
    question_id = first.snapshot_json["questions"][0]["id"]
    add_question(quiz, OPTION_B, question_id=question_id)
    second = authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    assert second.revision_no == 2
    # A is the answer of revision 1 only; revision 2 expects B.
    assert submit(run, started, OPTION_A).earned_points == 1
    stored = Attempt.objects.get(pk=started.attempt.pk)
    assert stored.status == Attempt.Status.SUBMITTED
    assert stored.revision_id == first.id
    assert list(Attempt.objects.filter(revision=first)) == [stored]
    assert not Attempt.objects.filter(revision=second).exists()


def test_repeated_submit_with_same_key_returns_same_result(run, started):
    first = submit(run, started, OPTION_A)
    assert submit(run, started, OPTION_B) == first
    assert Attempt.objects.get().score == 1


def test_repeated_submit_with_other_key_is_already_submitted(run, started):
    submit(run, started, OPTION_A)
    with pytest.raises(attempts.AttemptError) as error:
        submit(run, started, OPTION_A, key="other-key-1")
    assert error.value.code == "already_submitted"


def test_key_used_by_other_attempt_is_refused(run, started):
    submit(run, started, OPTION_A)
    other = attempts.start(run)
    with pytest.raises(attempts.AttemptError) as error:
        submit(run, other, OPTION_A)
    assert error.value.code == "submission_key_used"
    assert Attempt.objects.get(pk=other.attempt.pk).status == Attempt.Status.IN_PROGRESS


def test_lost_race_returns_the_winner_result(run, started):
    """Another request stores the result between the status check and the write."""
    real_score = attempts._score

    def score_then_lose(*args):
        result = real_score(*args)
        Attempt.objects.filter(pk=started.attempt.pk).update(
            status=Attempt.Status.SUBMITTED,
            submission_key=KEY,
            score=1,
            max_score=1,
            correct_count=1,
            submitted_at=timezone.now(),
        )
        return result

    with mock.patch.object(attempts, "_score", score_then_lose):
        result = submit(run, started, OPTION_B)
    assert result.earned_points == 1


@pytest.mark.parametrize(
    "answer", [{"options": ["nope"]}, {"options": [""]}, {"options": OPTION_A}, {"none": "x"}]
)
def test_malformed_answer_is_refused_and_attempt_can_still_submit(run, started, answer):
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, started.token, {question_id: answer}, KEY)
    assert error.value.code == "invalid_answer"
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS
    assert submit(run, started, OPTION_A).earned_points == 1


def test_unknown_question_id_is_ignored(run, started):
    answers = answers_for(run, OPTION_A) | {"no-such": {"options": ["x"]}}
    result = attempts.submit(started.attempt.id, started.token, answers, KEY)
    assert result.earned_points == 1


def test_token_of_other_attempt_is_refused(run, started):
    other = attempts.start(run)
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, other.token, {}, KEY)
    assert error.value.code == "invalid_token"


def test_garbage_token_is_refused(started):
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, "garbage", {}, KEY)
    assert error.value.code == "invalid_token"


def test_unknown_attempt_is_not_found(run):
    started = attempts.start(run)
    claims = replace(tokens.verify(started.token), attempt_id=uuid7())
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(claims.attempt_id, tokens.issue(claims), {}, KEY)
    assert error.value.code == "not_found"


@pytest.mark.parametrize(
    "change",
    [{"revision_id": uuid7()}, {"run_id": uuid7()}, {"manifest_hash": "tampered"}],
    ids=["revision", "run", "manifest"],
)
def test_correctly_signed_token_with_other_claims_is_refused(run, started, change):
    forged = tokens.issue(replace(tokens.verify(started.token), **change))
    with pytest.raises(attempts.AttemptError) as error:
        attempts.submit(started.attempt.id, forged, answers_for(run, OPTION_A), KEY)
    assert error.value.code == "invalid_token"
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS


def test_submit_after_run_closed_is_refused(run, started):
    authoring.close_run(run, admin_id=ADMIN_ID)
    with pytest.raises(attempts.AttemptError) as error:
        submit(run, started, OPTION_A)
    assert error.value.code == "run_closed"


def test_repeat_after_run_closed_still_returns_stored_result(run, started):
    first = submit(run, started, OPTION_A)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert submit(run, started, OPTION_A) == first


def test_expired_token_is_refused(run, started):
    expires = tokens.verify(started.token).expires_at
    late = expires + timedelta(seconds=1)
    with mock.patch("app.domain.attempts.timezone.now", return_value=late):
        with pytest.raises(attempts.AttemptError) as error:
            submit(run, started, OPTION_A)
    assert error.value.code == "attempt_expired"


def test_whole_boundary_second_is_accepted(run, started):
    expires = tokens.verify(started.token).expires_at.replace(microsecond=0)
    late = expires + timedelta(milliseconds=900)
    with mock.patch("app.domain.attempts.timezone.now", return_value=late):
        assert submit(run, started, OPTION_A).earned_points == 1


def test_disabled_type_still_scores_stored_revision(run, started):
    PluginInstallation.objects.update_or_create(
        pk="question.choice",
        defaults={"version": "1.0.0", "manifest_json": {}, "enabled": False},
    )
    assert submit(run, started, OPTION_A).earned_points == 1


def test_uninstalled_type_gives_revision_unavailable(run, started):
    revision = run.current_revision
    snapshot = revision.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    with pytest.raises(attempts.AttemptError) as error:
        submit(run, started, OPTION_A)
    assert error.value.code == "revision_unavailable"


def test_submit_emits_attempt_submitted_without_answers(run, started):
    with mock.patch("app.domain.attempts.events.emit") as emit:
        submit(run, started, OPTION_A)
    emit.assert_called_once()
    name, payload = emit.call_args.args
    assert name == "attempt.submitted"
    assert set(payload) == {"attempt_id", "run_id", "score", "max_score"}


def locked():
    return OperationalError("database is locked")


def test_with_retry_retries_locked_then_succeeds():
    function = mock.Mock(side_effect=[locked(), locked(), "done"])
    with mock.patch("app.domain.attempts.time.sleep") as sleep:
        assert attempts.with_retry(function) == "done"
    assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]


def test_with_retry_does_not_retry_other_errors():
    function = mock.Mock(side_effect=OperationalError("no such table"))
    with pytest.raises(OperationalError):
        attempts.with_retry(function)
    assert function.call_count == 1


def test_with_retry_gives_up_after_three_tries():
    function = mock.Mock(side_effect=locked())
    with mock.patch("app.domain.attempts.time.sleep"), pytest.raises(OperationalError):
        attempts.with_retry(function)
    assert function.call_count == 3


def test_start_freezes_selection_and_settings(db):
    run = open_quiz_run(questions=2)
    keep(run, settings.NAVIGATION_MODE, "step_back")
    keep(run, settings.REVEAL_MOMENT, "at_end")
    attempt = attempts.start(run).attempt
    attempt.refresh_from_db()
    expected = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    assert [item["id"] for item in attempt.selection_json["items"]] == expected
    assert attempt.selection_json["seed"] is None
    assert attempts.flow_of(attempt)["navigation"] == "step_back"
    assert attempts.flow_of(attempt)["moment"] == "at_end"
    assert attempts.flow_of(attempt)["level"] == "verdict"


def test_a_seed_is_stored_only_with_shuffled_options(db):
    run = open_quiz_run()
    keep(run, settings.SHUFFLE_OPTIONS, "on")
    assert attempts.option_seed(attempts.start(run).attempt)


def test_a_setting_change_does_not_touch_an_attempt_in_progress(db):
    run = open_quiz_run()
    attempt = attempts.start(run).attempt
    settings.set_override(settings.REVEAL_MOMENT, run.quiz, "at_end", admin_id=None)
    attempt.refresh_from_db()
    assert attempts.flow_of(attempt)["moment"] == "never"


def test_attempt_without_selection_plays_as_before(db):
    """In progress at the upgrade: no selection and no settings were stored."""
    run = open_quiz_run(questions=2)
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.pk).update(selection_json=None, settings_json=None)
    question_ids = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    answers = {qid: {"options": [OPTION_A]} for qid in question_ids}
    result = attempts.submit(started.attempt.id, started.token, answers, started.submission_key)
    assert result.earned_points == 2
    attempt = Attempt.objects.get(pk=started.attempt.pk)
    assert attempts.flow_of(attempt)["moment"] == "never"
    assert attempts.option_seed(attempt) is None


def test_an_answer_to_a_question_not_given_changes_nothing(db):
    run = open_quiz_run(questions=2)
    started = attempts.start(run)
    first, second = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    Attempt.objects.filter(pk=started.attempt.pk).update(
        selection_json={"items": [{"id": first, "draw": None}], "seed": None}
    )
    attempt = Attempt.objects.get(pk=started.attempt.pk)
    token = attempts._issue(attempt, attempt.started_at + attempts.ATTEMPT_LIFETIME)
    answers = {first: {"options": [OPTION_B]}, second: {"options": [OPTION_A]}}
    result = attempts.submit(started.attempt.id, token, answers, started.submission_key)
    assert result.earned_points == 0


def test_start_with_a_missing_plugin_stores_no_attempt(db):
    run = open_quiz_run()
    with mock.patch.object(attempts.registry, "get", side_effect=registry.UnknownPort("gone")):
        with pytest.raises(attempts.AttemptError) as error:
            attempts.start(run)
    assert error.value.code == "revision_unavailable"
    assert not Attempt.objects.exists()


def test_a_question_can_shuffle_when_the_quiz_does_not(db):
    quiz = make_quiz()
    config = definition(("cs",))
    shuffled = authoring.save_question(
        quiz, None, "choice", config, setting_values={settings.SHUFFLE_OPTIONS: "on"}
    )
    plain = authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    attempt = attempts.start(authoring.open_run(quiz, admin_id=ADMIN_ID)).attempt
    by_id = {q["id"]: q for q in attempts.questions_of(attempt)}
    assert attempts.option_seed_for(attempt, by_id[shuffled])
    assert attempts.option_seed_for(attempt, by_id[plain]) is None


def test_a_question_can_keep_its_order_when_the_quiz_shuffles(db):
    quiz = make_quiz()
    settings.set_override(settings.SHUFFLE_OPTIONS, quiz, "on", admin_id=ADMIN_ID)
    config = definition(("cs",))
    kept = authoring.save_question(
        quiz, None, "choice", config, setting_values={settings.SHUFFLE_OPTIONS: "off"}
    )
    plain = authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    attempt = attempts.start(authoring.open_run(quiz, admin_id=ADMIN_ID)).attempt
    by_id = {q["id"]: q for q in attempts.questions_of(attempt)}
    assert attempts.option_seed_for(attempt, by_id[kept]) is None
    assert attempts.option_seed_for(attempt, by_id[plain]) == attempts.option_seed(attempt)


def test_the_same_attempt_keeps_its_seed_for_a_question(db):
    quiz = make_quiz()
    authoring.save_question(
        quiz,
        None,
        "choice",
        definition(("cs",)),
        setting_values={settings.SHUFFLE_OPTIONS: "on"},
    )
    authoring.publish(quiz, admin_id=ADMIN_ID)
    attempt = attempts.start(authoring.open_run(quiz, admin_id=ADMIN_ID)).attempt
    question = attempts.questions_of(attempt)[0]
    first = attempts.option_seed_for(attempt, question)
    assert first and first == attempts.option_seed_for(attempt, question)


def test_an_attempt_from_before_b4_keeps_its_options_in_order(db):
    run = open_quiz_run()
    attempt = attempts.start(run).attempt
    attempt.selection_json = {**attempt.selection_json, "seed": None}
    attempt.save()
    assert attempts.option_seed_for(attempt, attempts.questions_of(attempt)[0]) is None


@pytest.mark.parametrize(
    "message,expected",
    [
        ("UNIQUE constraint failed: attempt.submission_key", True),
        ("UNIQUE constraint failed: attempt.id, attempt.submission_key", True),
        ("UNIQUE constraint failed: other.submission_key", False),
        ("UNIQUE constraint failed: attempt.id", False),
        ("NOT NULL constraint failed: attempt.submission_key", False),
    ],
)
def test_only_the_submission_key_constraint_means_a_used_key(message, expected):
    assert attempts._is_submission_key_conflict(IntegrityError(message)) is expected


def test_submitted_event_reaches_a_subscriber_once_when_the_store_is_retried(
    run, started, monkeypatch, django_capture_on_commit_callbacks
):
    """Documents the existing guarantee (it passes on the base too): events.emit defers the
    dispatch to the commit, so the callback of a rolled-back store is discarded and a retried
    store announces the submission once."""
    from app.kernel import events

    handled = []
    monkeypatch.setattr(events, "_handlers", {"attempt.submitted": [(handled.append, "test")]})
    monkeypatch.setattr(events, "is_enabled", lambda owner: True)
    real_emit = events.emit
    calls = []

    def emit_then_lose_the_lock(name, payload):
        real_emit(name, payload)
        calls.append(name)
        if len(calls) == 1:
            raise OperationalError("database is locked")

    monkeypatch.setattr(attempts.events, "emit", emit_then_lose_the_lock)
    monkeypatch.setattr(attempts.time, "sleep", lambda _: None)
    with django_capture_on_commit_callbacks(execute=True):
        submit(run, started, OPTION_A)
    assert len(calls) == 2  # the store really ran twice
    assert len(handled) == 1
