import importlib

import pytest
from django.apps import apps

from app.domain import attempts, authoring, settings, usage
from app.domain.models import QuizRevision, RunRevision
from app.kernel import lifecycle
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, add_question, open_quiz_run

pytestmark = pytest.mark.django_db
POLICY = settings.REVISION_SWITCH_POLICY


def change_question(run, correct=OPTION_B):
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    add_question(run.quiz, correct, question_id=question_id)


def publish_change(run, decision=None):
    change_question(run)
    revision = authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=decision)
    run.refresh_from_db()
    return revision


def submit(run, started, option):
    question_id = started.attempt.revision.snapshot_json["questions"][0]["id"]
    answers = {question_id: {"options": [option]}}
    return attempts.submit(started.attempt.id, started.token, answers, f"key-{started.attempt.id}")


def test_open_run_creates_first_row_with_finish():
    run = open_quiz_run()
    row = run.current_row()
    assert row.revision_id == run.current_revision_id
    assert row.switch_mode == RunRevision.SwitchMode.FINISH
    assert row.active_to is None
    assert row.max_score == run.current_revision.max_score


def test_let_finish_moves_new_attempts_to_new_revision():
    run = open_quiz_run()
    second = publish_change(run, authoring.Decision.LET_FINISH)
    assert run.current_revision_id == second.id
    assert attempts.start(run).attempt.revision_id == second.id
    assert run.current_row().switch_mode == RunRevision.SwitchMode.FINISH


def test_attempt_in_progress_stays_on_its_revision_after_let_finish():
    run = open_quiz_run()
    started = attempts.start(run)
    publish_change(run, authoring.Decision.LET_FINISH)
    assert submit(run, started, OPTION_A).earned_points == 1  # correct only on revision 1


def test_notify_switch_records_switch_mode_and_closes_previous_row():
    run = open_quiz_run()
    first_row = run.current_row()
    second = publish_change(run, authoring.Decision.NOTIFY_SWITCH)
    assert run.current_row().revision_id == second.id
    assert run.current_row().switch_mode == RunRevision.SwitchMode.SWITCH
    first_row.refresh_from_db()
    assert first_row.active_to is not None


def test_stay_leaves_round_and_writes_no_row():
    run = open_quiz_run()
    first = run.current_revision
    second = publish_change(run, authoring.Decision.STAY)
    assert run.current_revision_id == first.id and run.revision_rows.count() == 1
    assert second.status == QuizRevision.Status.PUBLISHED
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert authoring.open_run(run.quiz, admin_id=ADMIN_ID).current_revision_id == second.id


def test_stay_keeps_earlier_switch_decision():
    run = open_quiz_run()
    second = publish_change(run, authoring.Decision.NOTIFY_SWITCH)
    change_question(run, OPTION_A)
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.STAY)
    run.refresh_from_db()
    assert run.current_revision_id == second.id
    assert run.current_row().switch_mode == RunRevision.SwitchMode.SWITCH


def test_ask_without_decision_raises_and_changes_nothing():
    run = open_quiz_run()
    first = run.current_revision_id
    change_question(run)
    with pytest.raises(authoring.RoundDecisionRequired):
        authoring.publish(run.quiz, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.current_revision_id == first
    assert run.quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_unknown_decision_counts_as_none():
    run = open_quiz_run()
    change_question(run)
    with pytest.raises(authoring.RoundDecisionRequired):
        authoring.publish(run.quiz, admin_id=ADMIN_ID, decision="nope")


def test_stored_policy_applies_without_decision():
    run = open_quiz_run()
    settings.set_override(POLICY, run.quiz, "notify_switch", admin_id=ADMIN_ID)
    second = publish_change(run)
    assert run.current_revision_id == second.id
    assert run.current_row().switch_mode == RunRevision.SwitchMode.SWITCH


def test_decision_is_ignored_when_policy_is_stored():
    run = open_quiz_run()
    settings.set_global(POLICY, "let_finish", admin_id=ADMIN_ID)
    second = publish_change(run, authoring.Decision.STAY)
    assert run.current_revision_id == second.id


def test_no_open_round_needs_no_decision():
    run = open_quiz_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    change_question(run)
    assert authoring.publish(run.quiz, admin_id=ADMIN_ID).revision_no == 2


def test_round_outcome():
    run = open_quiz_run()
    assert authoring.round_outcome(run.quiz) == "ask"
    settings.set_override(POLICY, run.quiz, "let_finish", admin_id=ADMIN_ID)
    assert authoring.round_outcome(run.quiz) == "let_finish"
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert authoring.round_outcome(run.quiz) is None


def test_decision_is_audited():
    run = open_quiz_run()
    publish_change(run, authoring.Decision.NOTIFY_SWITCH)
    event = AuditEvent.objects.filter(action="quiz.published").order_by("-created_at").first()
    assert event.details_json["decision"] == "notify_switch"


def test_usage_counts_older_revisions_of_open_round():
    run = open_quiz_run()
    publish_change(run, authoring.Decision.LET_FINISH)
    newer = run.current_revision
    snapshot = newer.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=newer.pk).update(snapshot_json=snapshot)
    assert any("gone.type" in problem for problem in usage.missing_plugin_problems())
    old = run.revision_rows.exclude(revision=newer).get().revision
    snapshot = old.snapshot_json
    snapshot["questions"][0]["type"] = "older.gone"
    QuizRevision.objects.filter(pk=old.pk).update(snapshot_json=snapshot)
    assert any("older.gone" in problem for problem in usage.missing_plugin_problems())


def test_plugin_of_older_revision_cannot_be_disabled():
    run = open_quiz_run()
    publish_change(run, authoring.Decision.LET_FINISH)
    newer = run.current_revision
    snapshot = newer.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=newer.pk).update(snapshot_json=snapshot)
    with pytest.raises(lifecycle.ModuleInUse):
        lifecycle.set_enabled("question.choice", False, actor_type="admin", actor_id=ADMIN_ID)


def test_data_migration_creates_rows_for_existing_rounds():
    run = open_quiz_run()
    run.revision_rows.all().delete()
    module = importlib.import_module("app.domain.migrations.0003_runrevision_attempt_switched")
    module.create_rows(apps, None)
    row = run.current_row()
    assert row.revision_id == run.current_revision_id
    assert row.active_from == run.opened_at
    assert row.switch_mode == RunRevision.SwitchMode.FINISH
    assert row.max_score == run.current_revision.max_score
