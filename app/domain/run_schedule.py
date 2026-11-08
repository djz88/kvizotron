"""What a run does over time: a plan opens, a deadline closes (FR-10, FR-11, ADR-0048).

Nothing runs in the background. `settle` applies what is due on the first request after it, and
whoever reads a run's status gets the result. Whether a submission counts never depends on this:
`attempts` compares against the deadline itself.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from app.domain import authoring, clock, data_policy, participants, requirements, settings
from app.domain import results as run_results
from app.domain import rewards as run_rewards
from app.domain.models import Attempt, Quiz, QuizRun, RunRevision
from app.kernel import audit, events
from app.kernel.models import AuditEvent

DEADLINE_NOTICE = timedelta(seconds=60)  # open pages ask for the time every 30 s


class ScheduleRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _system_audit(action: str, run: QuizRun) -> None:
    audit.record(
        actor_type="system",
        actor_id=None,
        action=action,
        entity_type="run",
        entity_id=str(run.id),
    )


def _admin_audit(action: str, run: QuizRun, admin_id: str, details: dict | None = None) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="run",
        entity_id=str(run.id),
        details=details,
    )


def _open(run: QuizRun, when: datetime) -> bool:
    """False when another request got there first. The caller is inside a transaction."""
    changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.SCHEDULED).update(
        status=QuizRun.Status.OPEN, opened_at=when
    )
    if not changed:
        return False
    revision = QuizRun.objects.get(pk=run.pk).current_revision
    RunRevision.objects.create(
        run=run, revision=revision, active_from=when, max_score=revision.max_score
    )
    events.emit("run.opened", {"run_id": str(run.id)})
    return True


def _unmet(run: QuizRun) -> list[requirements.Requirement]:
    snapshot = run.current_revision.snapshot_json
    return requirements.unmet(run.quiz, requirements.of_snapshot(snapshot, run.quiz))


def _stateless_conflicts(run: QuizRun) -> list[str]:
    return data_policy.conflicts(
        data_policy.of(run)[data_policy.PROFILE],
        participants.rules_of(run),
        settings.resolve(settings.ANSWERS_VISIBILITY, run.quiz),
        run.current_revision.snapshot_json,
    )


def _refuse_opening(run: QuizRun, keys: list[str]) -> None:
    """Once per cause, as `settle` runs on every request."""
    seen = AuditEvent.objects.filter(
        action="run.open_refused", entity_id=str(run.id), details_json={"keys": keys}
    )
    if not seen.exists():
        audit.record(
            actor_type="system",
            actor_id=None,
            action="run.open_refused",
            entity_type="run",
            entity_id=str(run.id),
            details={"keys": keys},
        )


def _open_due(now: datetime) -> None:
    due = QuizRun.objects.filter(status=QuizRun.Status.SCHEDULED, starts_at__lte=now)
    for run in due.select_related("quiz", "current_revision"):
        if _unmet(run):
            continue  # stays planned, and the quiz's page says why
        refused = _stateless_conflicts(run) + run_rewards.conflicts(run)
        if refused:
            _refuse_opening(run, refused)
            continue
        with transaction.atomic():
            if _open(run, run.starts_at or now):
                _system_audit("run.opened", run)


def _close_due(now: datetime) -> None:
    due = QuizRun.objects.filter(
        status=QuizRun.Status.OPEN, deadline_at__lt=clock.whole_second(now)
    )
    for run in due:
        with transaction.atomic():
            changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.OPEN).update(
                status=QuizRun.Status.CLOSED, closed_at=F("deadline_at")
            )
            if changed:
                _system_audit("run.closed", run)
                events.emit("run.closed", {"run_id": str(run.id)})


def settle(now: datetime | None = None) -> None:
    """Idempotent, and writes nothing when nothing is due. Test runs have no schedule."""
    now = now or timezone.now()
    _open_due(now)
    _close_due(now)


def planned_run(quiz: Quiz) -> QuizRun | None:
    return quiz.runs.filter(status=QuizRun.Status.SCHEDULED).first()


def _check_plan(starts_at: datetime, deadline_at: datetime | None) -> None:
    if starts_at <= timezone.now():
        raise ScheduleRefused("start_in_past")
    if deadline_at is not None and deadline_at <= starts_at:
        raise ScheduleRefused("deadline_before_start")


def plan(
    quiz: Quiz,
    *,
    starts_at: datetime,
    deadline_at: datetime | None,
    limit_sec: int | None,
    admin_id: str,
    rules: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
    results: Mapping[str, str] | None = None,
    rewards: Mapping[str, str] | None = None,
) -> QuizRun:
    authoring.ensure_editable(quiz)
    _check_plan(starts_at, deadline_at)
    revision = authoring.latest_published(quiz)
    if revision is None:
        raise authoring.NothingPublished(str(quiz.id))
    missing = requirements.unmet(quiz, requirements.of_snapshot(revision.snapshot_json, quiz))
    if missing:
        raise authoring.RequirementUnmet([item.text for item in missing])
    last = quiz.runs.aggregate(last=Max("run_no"))["last"] or 0
    chosen_rules = participants.snapshot(quiz, rules)
    chosen_data = data_policy.snapshot(quiz, data)
    data_policy.ensure_run_allowed(quiz, chosen_data, chosen_rules, revision.snapshot_json)
    chosen_results = run_results.snapshot(quiz, results)
    run_results.ensure_run_allowed(quiz, chosen_results, chosen_data[data_policy.PROFILE])
    try:
        with transaction.atomic():
            run = QuizRun.objects.create(
                quiz=quiz,
                run_no=last + 1,
                current_revision=revision,
                status=QuizRun.Status.SCHEDULED,
                opened_at=None,
                starts_at=starts_at,
                deadline_at=deadline_at,
                attempt_limit_sec=limit_sec,
                participant_rules_json=chosen_rules,
                retention_json=chosen_data,
                results_json=chosen_results,
                rewards_json=run_rewards.snapshot(quiz, rewards),
            )
            run_rewards.copy_rules(run)
            run_rewards.ensure_allowed(run)
            _admin_audit("run.planned", run, admin_id)
    except IntegrityError as exc:
        raise ScheduleRefused("already_planned") from exc
    return run


def open_now(
    quiz: Quiz,
    *,
    deadline_at: datetime | None,
    limit_sec: int | None,
    admin_id: str,
    rules: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
    results: Mapping[str, str] | None = None,
    rewards: Mapping[str, str] | None = None,
) -> QuizRun:
    """The plan form with no start."""
    if deadline_at is not None and deadline_at <= timezone.now():
        raise ScheduleRefused("deadline_before_start")
    return authoring.open_run(
        quiz,
        admin_id=admin_id,
        deadline_at=deadline_at,
        limit_sec=limit_sec,
        rules=rules,
        data=data,
        results=results,
        rewards=rewards,
    )


def update_plan(
    run: QuizRun,
    *,
    starts_at: datetime,
    deadline_at: datetime | None,
    limit_sec: int | None,
    admin_id: str,
    rules: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
    results: Mapping[str, str] | None = None,
    rewards: Mapping[str, str] | None = None,
) -> None:
    _check_plan(starts_at, deadline_at)
    chosen_rules = participants.snapshot(run.quiz, rules)
    chosen_data = data_policy.snapshot(run.quiz, data)
    data_policy.ensure_run_allowed(
        run.quiz, chosen_data, chosen_rules, run.current_revision.snapshot_json
    )
    chosen_results = run_results.snapshot(run.quiz, results) | {
        run_results.SEED: run_results.of(run)[run_results.SEED]
    }
    run_results.ensure_run_allowed(run.quiz, chosen_results, chosen_data[data_policy.PROFILE])
    with transaction.atomic():
        changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.SCHEDULED).update(
            starts_at=starts_at,
            deadline_at=deadline_at,
            attempt_limit_sec=limit_sec,
            participant_rules_json=chosen_rules,
            retention_json=chosen_data,
            results_json=chosen_results,
            rewards_json=run_rewards.snapshot(run.quiz, rewards),
        )
        if not changed:
            raise ScheduleRefused("not_planned")
        run_rewards.ensure_allowed(QuizRun.objects.get(pk=run.pk))
        _admin_audit("run.plan_changed", run, admin_id)


def set_period(run: QuizRun, period: str, *, admin_id: str) -> None:
    """The period can change at any time; the profile cannot, as attempts already follow it."""
    if period not in settings.CATALOGUE[settings.RETENTION_PERIOD].choices:
        raise ScheduleRefused("invalid_period")
    if run.kind == QuizRun.Kind.TEST:
        raise ScheduleRefused("not_a_normal_run")
    with transaction.atomic():
        current = QuizRun.objects.select_for_update().filter(pk=run.pk).first()
        if current is None:  # `objects` holds normal runs only
            raise ScheduleRefused("not_a_normal_run")
        current.retention_json = data_policy.of(current) | {data_policy.PERIOD: period}
        current.save(update_fields=["retention_json"])
        _admin_audit("run.period_changed", run, admin_id, {"period": period})


def cancel_plan(run: QuizRun, *, admin_id: str) -> None:
    """No attempt can exist yet, so the row goes and its number is free."""
    with transaction.atomic():
        deleted, _rows = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.SCHEDULED).delete()
        if not deleted:
            raise ScheduleRefused("not_planned")
        _admin_audit("run.plan_cancelled", run, admin_id)


def start_now(run: QuizRun, *, admin_id: str) -> None:
    now = timezone.now()
    missing = _unmet(run)
    if missing:
        raise authoring.RequirementUnmet([item.text for item in missing])
    refused = _stateless_conflicts(run)
    if refused:
        raise data_policy.StatelessConflict(refused)
    run_rewards.ensure_allowed(run)
    if run.deadline_at is not None and run.deadline_at <= now:
        raise ScheduleRefused("deadline_before_start")
    with transaction.atomic():
        if not _open(run, now):
            raise ScheduleRefused("not_planned")
        _admin_audit("run.opened", run, admin_id)


def set_deadline(run: QuizRun, deadline_at: datetime | None, *, admin_id: str) -> None:
    """Applies to attempts in progress too, as they compare against the run's value."""
    if deadline_at is not None and deadline_at < timezone.now() + DEADLINE_NOTICE:
        raise ScheduleRefused("deadline_too_soon")
    with transaction.atomic():
        before = QuizRun.objects.filter(pk=run.pk).values_list("deadline_at", flat=True).first()
        changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.OPEN).update(
            deadline_at=deadline_at
        )
        if not changed:
            raise ScheduleRefused("not_open")
        _admin_audit(
            "run.deadline_changed",
            run,
            admin_id,
            {
                "from": before.isoformat() if before else None,
                "to": deadline_at.isoformat() if deadline_at else None,
            },
        )


def archive(run: QuizRun, *, admin_id: str) -> None:
    """Hides an ended run in admin and from the public walkthrough. Nothing is deleted."""
    with transaction.atomic():
        changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.CLOSED).update(
            status=QuizRun.Status.ARCHIVED
        )
        if not changed:
            raise ScheduleRefused("not_ended")
        _admin_audit("run.archived", run, admin_id)


def restore(run: QuizRun, *, admin_id: str) -> None:
    with transaction.atomic():
        changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.ARCHIVED).update(
            status=QuizRun.Status.CLOSED
        )
        if not changed:
            raise ScheduleRefused("not_ended")
        _admin_audit("run.restored", run, admin_id)


def unsent(run: QuizRun, now: datetime | None = None) -> int:
    """Attempts that will never arrive. A replaced attempt has another status, so it is not one."""
    waiting = run.attempts.filter(status=Attempt.Status.IN_PROGRESS)
    if run.status != QuizRun.Status.OPEN:
        return waiting.count()
    if not run.attempt_limit_sec:
        return 0
    moment = clock.whole_second(now or timezone.now())
    return waiting.filter(started_at__lt=moment - timedelta(seconds=run.attempt_limit_sec)).count()


def in_progress(run: QuizRun) -> int:
    return run.attempts.filter(status=Attempt.Status.IN_PROGRESS).count()
