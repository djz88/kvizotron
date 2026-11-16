"""Deleting a run's data and keeping its summary: one code path for expiry and for an admin."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db.models import ProtectedError
from django.utils import timezone

from app.domain import authoring, data_policy, retention, run_stats
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Draw,
    DrawEntry,
    HiddenAnswerValue,
    Participant,
    QuizRevision,
    QuizRun,
    RewardEntitlement,
    RewardRule,
    RunRevision,
)
from app.kernel import events, registry
from app.kernel.models import AuditEvent
from app.providers.csv_io.models import ExportJobRecord
from app.providers.media_local.models import MediaAsset
from app.providers.retention.models import RetentionJob
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
COUNTS = {
    "attempts": 3,
    "answers": 3,
    "participants": 2,
    "entitlements": 1,
    "hidden_values": 1,
    "photos": 1,
}


@pytest.fixture(autouse=True)
def media_path(settings, tmp_path):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def a_run(slug="kviz", profile="answers"):
    return authoring.open_run(
        published_quiz(slug, questions=2), admin_id=ADMIN_ID, data={"profile": profile}
    )


def asset(path):
    asset_id = uuid4()
    MediaAsset.objects.create(
        id=asset_id,
        storage_key=f"{asset_id}.webp",
        mime_type="image/webp",
        size=1,
        sha256="0" * 64,
        private=True,
    )
    (path / f"{asset_id}.webp").write_bytes(b"x")
    return str(asset_id)


def question_ids(run):
    return [q["id"] for q in run.current_revision.snapshot_json["questions"]]


def attempt(run, who, score, *, status=Attempt.Status.SUBMITTED, answers=()):
    found = Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=status,
        submitted_at=timezone.now() if status in Attempt.FINISHED else None,
        score=None if score is None else Decimal(score),
        max_score=run.current_revision.max_score,
    )
    for question_id, points, asset_id in answers:
        AttemptAnswer.objects.create(
            attempt=found,
            question_id=question_id,
            answer_json={},
            auto_points=Decimal(points),
            asset_id=asset_id,
        )
    return found


def reward_rule(run):
    return RewardRule.objects.create(quiz=run.quiz, run=run, kind=RewardRule.Kind.DRAW, winners=1)


def draw_entry(run, rule, who):
    draw = Draw.objects.create(
        run=run,
        rule=rule,
        action=Draw.Action.DRAW,
        admin_id=ADMIN_ID,
        eligible_count=2,
        eligible_set_hash="h",
        algorithm="a",
        rules_version="v",
    )
    return DrawEntry.objects.create(
        draw=draw, participant=who, pseudonym="pseudo", position=1, role=DrawEntry.Role.WINNER
    )


def filled(path, slug="kviz", profile="answers"):
    """Holds what `COUNTS` says. The first person's first attempt was replaced by the second."""
    run = a_run(slug, profile)
    first, second = question_ids(run)
    a = Participant.objects.create(
        run=run, anonymous_key_hash="a", display_name="Jana", email="jana@example.org"
    )
    b = Participant.objects.create(run=run, anonymous_key_hash="b", display_name="Eva")
    old = attempt(run, a, None, status=Attempt.Status.ABANDONED)
    new = attempt(run, a, 2, answers=[(first, 1, asset(path)), (second, 1, None)])
    Attempt.objects.filter(pk=old.pk).update(replaced_by=new)
    attempt(run, b, 1, answers=[(first, 1, None)])
    HiddenAnswerValue.objects.create(run=run, question_id=first, value_key="k", hidden_by=ADMIN_ID)
    rule = reward_rule(run)
    RewardEntitlement.objects.create(
        run=run, rule=rule, participant=a, source=RewardEntitlement.Source.DRAW
    )
    draw_entry(run, rule, a)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    return run


def purged(run, *, trigger="automatic", admin_id=None):
    return retention.purge_run(run, trigger=trigger, admin_id=admin_id)


def rows_of(run):
    return {
        "participants": Participant.objects.filter(run=run).count(),
        "attempts": Attempt.objects.filter(run=run).count(),
        "answers": AttemptAnswer.objects.filter(attempt__run=run).count(),
        "entitlements": RewardEntitlement.objects.filter(run=run).count(),
        "hidden": HiddenAnswerValue.objects.filter(run=run).count(),
    }


NOTHING = {"participants": 0, "attempts": 0, "answers": 0, "entitlements": 0, "hidden": 0}


def records(run):
    return list(RetentionJob.objects.filter(run_id=str(run.id)))


def test_everything_personal_goes_and_the_rest_stays(media_path):
    """AC-14, AC-111: rows and photos go; the run, revisions, rules and pseudonymous draws stay."""
    run = filled(media_path)
    photos = list(MediaAsset.objects.values_list("pk", flat=True))

    assert purged(run) is True

    assert rows_of(run) == NOTHING
    assert not MediaAsset.objects.filter(pk__in=photos).exists()
    assert not list(media_path.glob("*.webp"))
    run.refresh_from_db()
    assert run.status == QuizRun.Status.ARCHIVED
    assert run.data_deleted_at is not None
    assert run.retention_held_at is None
    assert data_policy.of(run)[data_policy.PROFILE] == "none"
    assert run.stateless_submitted == 2
    assert QuizRevision.objects.filter(pk=run.current_revision_id).exists()
    assert RunRevision.objects.filter(run=run).exists()
    assert RewardRule.objects.filter(run=run).count() == 1
    entry = DrawEntry.objects.get(draw__run=run)
    assert entry.pseudonym == "pseudo"
    assert entry.participant_id is None


def test_another_run_is_left_alone(media_path):
    """AC-111."""
    run = filled(media_path)
    other = filled(media_path, slug="jiny")
    before = rows_of(other)
    assets = MediaAsset.objects.count()

    purged(run)

    assert rows_of(other) == before
    assert MediaAsset.objects.count() == assets - 1
    assert DrawEntry.objects.get(draw__run=other).participant_id is not None


def test_a_replaced_by_chain_deletes(media_path):
    """AC-111: the attempts protect each other until the chain is untied."""
    run = filled(media_path)
    assert Attempt.objects.filter(run=run, replaced_by__isnull=False).exists()

    assert purged(run) is True

    assert not Attempt.objects.filter(run=run).exists()


def test_a_photo_file_already_missing_does_not_stop_it(media_path):
    """AC-111."""
    run = filled(media_path)
    for found in media_path.glob("*.webp"):
        found.unlink()

    assert purged(run) is True

    assert rows_of(run) == NOTHING
    assert not MediaAsset.objects.exists()


def test_a_photo_that_cannot_be_deleted_does_not_stop_it_and_logs_only_the_run(
    media_path, monkeypatch, caplog
):
    """AC-111: the sweep of a later pass finds the file."""
    run = filled(media_path)
    storage = registry.get("media_storage", registry.keys("media_storage")[0])

    def refuse(_asset_id):
        raise OSError("jana@example.org")

    monkeypatch.setattr(type(storage), "delete_image", lambda _self, asset_id: refuse(asset_id))

    assert purged(run) is True

    assert rows_of(run) == NOTHING
    assert str(run.id) in caplog.text
    assert "jana@example.org" not in caplog.text


def test_purging_twice_leaves_one_record(media_path):
    """AC-111."""
    run = filled(media_path)

    assert purged(run) is True
    assert purged(run) is False

    assert len(records(run)) == 1
    assert AuditEvent.objects.filter(action="run.data_deleted", entity_id=str(run.id)).count() == 1


def test_a_stale_run_object_is_not_purged_twice(media_path):
    """AC-111: the caller may hold a copy read before the first purge."""
    run = filled(media_path)
    stale = QuizRun.objects.get(pk=run.pk)

    purged(run)

    assert purged(stale) is False
    assert len(records(run)) == 1


def test_a_failure_after_the_summary_resumes_with_the_original_counts(media_path, monkeypatch):
    """AC-111: stage 1 and one batch committed, so the second purge finds less than was there."""
    run = filled(media_path)
    real = retention._delete_batch
    monkeypatch.setattr(retention, "BATCH", 1)
    calls = []

    def breaks_after_one(run_id):
        calls.append(run_id)
        found = real(run_id)
        if len(calls) == 1:
            raise RuntimeError("simulated")
        return found

    monkeypatch.setattr(retention, "_delete_batch", breaks_after_one)
    with pytest.raises(RuntimeError):
        purged(run)
    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert run.retention_summary_json["counts"] == COUNTS
    assert Attempt.objects.filter(run=run).count() == 2

    assert purged(run) is True

    (record,) = records(run)
    assert record.counts_json == COUNTS
    assert rows_of(run) == NOTHING


def test_many_attempts_go_in_batches(media_path, monkeypatch):
    """AC-111."""
    run = a_run()
    monkeypatch.setattr(retention, "BATCH", 2)
    for _ in range(5):
        attempt(run, None, 1)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()

    assert purged(run) is True

    assert not Attempt.objects.filter(run=run).exists()
    assert records(run)[0].counts_json["attempts"] == 5


def test_the_record_and_audit_say_who_and_how_much_and_no_more(media_path):
    """AC-111."""
    run = filled(media_path)
    cutoff = data_policy.deletion_at(run)
    policy = data_policy.of(run)[data_policy.PERIOD]

    purged(run)

    (record,) = records(run)
    assert record.trigger == "automatic"
    assert record.admin_id is None
    assert record.policy == policy
    assert record.cutoff_at == cutoff
    assert record.counts_json == COUNTS
    event = AuditEvent.objects.get(action="run.data_deleted", entity_id=str(run.id))
    assert event.actor_type == "system"
    assert event.actor_id is None
    assert event.entity_type == "run"
    assert event.details_json == {"counts": COUNTS}
    assert "jana" not in str(event.details_json).lower()


def test_the_event_names_only_the_run_and_is_sent_once(
    media_path, monkeypatch, django_capture_on_commit_callbacks
):
    """AC-111."""
    run = filled(media_path)
    seen = []
    monkeypatch.setitem(events._handlers, "retention.executed", [(seen.append, "retention.local")])

    with django_capture_on_commit_callbacks(execute=True):
        purged(run)
    with django_capture_on_commit_callbacks(execute=True):
        purged(run)

    assert seen == [{"run_id": str(run.id)}]


def test_an_export_naming_the_run_goes_with_the_data(media_path):
    """AC-111."""
    run = filled(media_path)
    job, directory = done_export(media_path, run)

    purged(run)

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def done_export(media_path, run):
    now = timezone.now()
    job = ExportJobRecord.objects.create(
        admin_id="a",
        kind="results",
        status="done",
        choices_json={"quiz": str(run.quiz_id), "runs": [str(run.id)], "all_runs": False},
        report_json={"files": ["x.csv"], "error": None},
        boot="x",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    directory = media_path / "exports" / str(job.pk)
    directory.mkdir(parents=True)
    (directory / "x.csv").write_text("x")
    return job, directory


def test_an_export_that_cannot_be_removed_stops_the_purge_and_the_next_one_removes_it(
    media_path, monkeypatch
):
    """AC-111: an export must not outlive the run's data, so the run is not yet recorded deleted."""
    run = filled(media_path)
    job, directory = done_export(media_path, run)
    exporter = registry.get("results_exporter", "csv")
    real = type(exporter).delete_for_runs
    calls = []

    def fails_once(self, quiz_id, run_ids):
        calls.append(run_ids)
        if len(calls) == 1:
            raise OSError("disk")
        real(self, quiz_id, run_ids)

    monkeypatch.setattr(type(exporter), "delete_for_runs", fails_once)

    with pytest.raises(OSError):
        purged(run)
    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert not records(run)
    assert directory.exists()

    assert purged(run) is True

    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()
    (record,) = records(run)
    assert record.counts_json == COUNTS


def test_an_export_left_after_the_commit_does_not_undo_the_deletion(
    media_path, monkeypatch, caplog
):
    """AC-111: the call after the commit is only for a job created during the purge."""
    run = filled(media_path)
    exporter = registry.get("results_exporter", "csv")
    real = type(exporter).delete_for_runs
    calls = []

    def fails_the_second_time(self, quiz_id, run_ids):
        calls.append(run_ids)
        if len(calls) == 2:
            raise OSError("disk")
        real(self, quiz_id, run_ids)

    monkeypatch.setattr(type(exporter), "delete_for_runs", fails_the_second_time)

    assert purged(run) is True

    assert len(calls) == 2
    assert str(run.id) in caplog.text
    assert len(records(run)) == 1


def test_an_export_created_during_the_purge_goes_too(media_path, monkeypatch):
    """AC-111: it appeared after the first removal, while the run was being finished."""
    run = filled(media_path)
    real = retention._finish
    made = []

    def export_arrives(*args):
        made.append(done_export(media_path, run))
        return real(*args)

    monkeypatch.setattr(retention, "_finish", export_arrives)

    assert purged(run) is True

    ((job, directory),) = made
    assert not ExportJobRecord.objects.filter(pk=job.pk).exists()
    assert not directory.exists()


def test_without_an_exporter_the_purge_still_finishes(media_path, monkeypatch, caplog):
    """AC-111: no exporter means no export files, not a removal that failed."""
    run = filled(media_path)
    real = registry.get

    def no_exporter(port, key, **kwargs):
        if port == "results_exporter":
            raise LookupError(port)
        return real(port, key, **kwargs)

    monkeypatch.setattr(registry, "get", no_exporter)

    assert purged(run) is True

    assert len(records(run)) == 1
    assert f"Run {run.id}: no results exporter" in caplog.text
    assert "jana@example.org" not in caplog.text


def test_a_chain_made_after_the_summary_does_not_block_a_resume(media_path, monkeypatch):
    """AC-111: stage 1 does not run again, and a batch must not meet a protected attempt."""
    run = filled(media_path)
    real = retention._delete_batch
    monkeypatch.setattr(retention, "BATCH", 1)

    def stops_first(_run_id):
        raise RuntimeError("simulated")

    monkeypatch.setattr(retention, "_delete_batch", stops_first)
    with pytest.raises(RuntimeError):
        purged(run)
    monkeypatch.setattr(retention, "_delete_batch", real)
    first, second, _third = Attempt.objects.filter(run=run).order_by("pk")
    Attempt.objects.filter(pk=second.pk).update(replaced_by=first)

    assert purged(run) is True

    assert not Attempt.objects.filter(run=run).exists()


def test_delete_now_matches_expiry(media_path):
    """AC-115: the same result by the same code path, and it names the admin."""
    by_expiry = filled(media_path)
    by_admin = filled(media_path, slug="jiny")

    purged(by_expiry)
    retention.delete_now(by_admin, admin_id=ADMIN_ID)

    by_expiry.refresh_from_db()
    by_admin.refresh_from_db()
    assert rows_of(by_admin) == NOTHING
    assert by_admin.status == by_expiry.status == QuizRun.Status.ARCHIVED
    # The quizzes differ only in their questions' ids, and the summary keeps who asked.
    own = {"questions", "trigger", "admin_id"}
    assert {k: v for k, v in by_admin.retention_summary_json.items() if k not in own} == {
        k: v for k, v in by_expiry.retention_summary_json.items() if k not in own
    }
    assert by_admin.retention_summary_json["trigger"] == "manual"
    assert by_expiry.retention_summary_json["trigger"] == "automatic"
    (record,) = records(by_admin)
    assert record.trigger == "manual"
    assert record.admin_id == ADMIN_ID
    event = AuditEvent.objects.get(action="run.data_deleted", entity_id=str(by_admin.id))
    assert event.actor_type == "admin"
    assert event.actor_id == ADMIN_ID


def test_delete_now_works_on_an_archived_run(media_path):
    """AC-115."""
    run = filled(media_path)
    QuizRun.objects.filter(pk=run.pk).update(status=QuizRun.Status.ARCHIVED)
    run.refresh_from_db()

    retention.delete_now(run, admin_id=ADMIN_ID)

    assert rows_of(run) == NOTHING


def test_delete_now_is_refused_on_an_open_run(media_path):
    """AC-115."""
    run = a_run()
    attempt(run, None, 1)

    with pytest.raises(retention.Refused) as refused:
        retention.delete_now(run, admin_id=ADMIN_ID)

    assert refused.value.code == "not_ended"
    assert Attempt.objects.filter(run=run).count() == 1
    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert not records(run)


def test_a_failure_inside_the_final_commit_leaves_nothing_half_done(media_path, monkeypatch):
    """AC-111: the rows, the mark and the record are one transaction, and a retry finishes it."""
    run = filled(media_path)
    trail = registry.get("retention", "local")

    def breaks(*args, **kwargs):
        raise RuntimeError("simulated")

    with monkeypatch.context() as patched:
        patched.setattr(type(trail), "record", breaks)
        with pytest.raises(RuntimeError):
            purged(run, trigger="manual", admin_id=ADMIN_ID)

    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert run.status == QuizRun.Status.CLOSED
    assert run.retention_summary_json["counts"] == COUNTS
    assert "late_exports_pending" not in run.retention_summary_json
    assert Participant.objects.filter(run=run).count() == 2
    assert HiddenAnswerValue.objects.filter(run=run).count() == 1
    assert RewardEntitlement.objects.filter(run=run).count() == 1
    assert not records(run)
    assert not AuditEvent.objects.filter(action="run.data_deleted", entity_id=str(run.id))

    assert purged(run) is True

    (record,) = records(run)
    assert (record.trigger, record.admin_id) == ("manual", ADMIN_ID)
    assert record.counts_json == COUNTS
    assert rows_of(run) == NOTHING


def test_a_protected_row_met_in_the_final_commit_leaves_it_resumable(media_path, monkeypatch):
    """AC-111: an attempt made after the batches protects its person; the next pass clears it."""
    run = filled(media_path)
    real = retention._delete_exports

    def then_a_late_attempt(found):
        real(found)
        late = Participant.objects.filter(run=found).order_by("pk").last()
        attempt(found, late, None, status=Attempt.Status.IN_PROGRESS)

    with monkeypatch.context() as patched:
        patched.setattr(retention, "_delete_exports", then_a_late_attempt)
        with pytest.raises(ProtectedError):
            purged(run)

    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert Participant.objects.filter(run=run).count() == 2
    assert HiddenAnswerValue.objects.filter(run=run).count() == 1
    assert RewardEntitlement.objects.filter(run=run).count() == 1
    assert Attempt.objects.filter(run=run).count() == 1
    assert not records(run)

    assert purged(run) is True

    (record,) = records(run)
    assert record.counts_json == COUNTS
    assert rows_of(run) == NOTHING


def test_delete_now_is_refused_on_a_scheduled_run(media_path):
    """AC-115: a run that has not begun keeps what it has, and nothing is recorded."""
    run = a_run()
    attempt(run, None, 1)
    QuizRun.objects.filter(pk=run.pk).update(status=QuizRun.Status.SCHEDULED)
    run.refresh_from_db()

    with pytest.raises(retention.Refused) as refused:
        retention.delete_now(run, admin_id=ADMIN_ID)

    assert refused.value.code == "not_ended"
    assert retention.deletable(run) is False
    assert Attempt.objects.filter(run=run).count() == 1
    run.refresh_from_db()
    assert run.data_deleted_at is None
    assert not run.retention_summary_json
    assert not records(run)


def test_delete_now_does_not_trust_a_stale_status(media_path):
    """AC-115: a copy read while the run was closed says nothing about it now."""
    run = filled(media_path)
    QuizRun.objects.filter(pk=run.pk).update(status=QuizRun.Status.OPEN)

    with pytest.raises(retention.Refused):
        retention.delete_now(run, admin_id=ADMIN_ID)


def test_a_run_with_no_attempts_purges_cleanly(media_path):
    """AC-111."""
    run = a_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()

    assert purged(run) is True

    run.refresh_from_db()
    assert run.status == QuizRun.Status.ARCHIVED
    assert run.stateless_submitted == 0
    assert records(run)[0].counts_json == dict.fromkeys(COUNTS, 0)


def test_a_run_with_profile_none_purges_cleanly_and_keeps_its_count(media_path):
    """AC-111: only unsubmitted attempts can remain, and the counter is the whole result."""
    run = a_run(profile="none")
    QuizRun.objects.filter(pk=run.pk).update(stateless_submitted=7)
    attempt(run, None, None, status=Attempt.Status.IN_PROGRESS)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()

    assert purged(run) is True

    run.refresh_from_db()
    assert run.stateless_submitted == 7
    assert not Attempt.objects.filter(run=run).exists()
    assert run_stats.of_run(run).submitted == 7


def test_a_held_run_stops_being_held(media_path):
    """AC-111: whoever deletes it has decided."""
    run = filled(media_path)
    QuizRun.objects.filter(pk=run.pk).update(retention_held_at=timezone.now())
    run.refresh_from_db()

    purged(run)

    run.refresh_from_db()
    assert run.retention_held_at is None


def test_the_period_stays_on_the_run(media_path):
    """AC-111: only the profile is rewritten."""
    run = filled(media_path)
    period = data_policy.of(run)[data_policy.PERIOD]

    purged(run)

    run.refresh_from_db()
    assert data_policy.of(run)[data_policy.PERIOD] == period
    assert data_policy.deletion_at(run) is None


def test_the_caller_sees_the_run_as_it_ended(media_path):
    run = filled(media_path)

    purged(run)

    assert run.data_deleted_at is not None
    assert run.status == QuizRun.Status.ARCHIVED
