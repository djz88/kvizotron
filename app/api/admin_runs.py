"""The runs tab, a run's page, ending it, and the quiz's QR code (FR-02)."""

import contextlib
import io
from datetime import datetime
from typing import Any
from uuid import UUID

import segno
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from app.api import admin_view
from app.api.admin_auth import admin_required
from app.api.admin_forms import RunPlanForm, conflict_messages, result_messages
from app.api.admin_quizzes import not_archived, run_open
from app.api.admin_workspace import workspace
from app.api.rendering import page, question_label
from app.contracts import (
    ASK_EMAIL,
    OFFICIAL_ATTEMPT,
    RESULT_DISPLAY_KEYS,
    TIE_BREAK_POLICY,
    WINNER_CONTACT,
)
from app.domain import (
    access_codes,
    attempts,
    authoring,
    clock,
    data_policy,
    participants,
    results,
    revision_diff,
    rewards,
    run_schedule,
    run_stats,
    settings,
    walkthrough,
)
from app.domain.models import Attempt, Quiz, QuizRun, RewardRule


def _submitted(run: QuizRun, counted: int) -> int:
    """Under "nothing" no attempt row stays, so the run's own count is the number."""
    if data_policy.is_stateless(attempts.effective_profile(run)):
        return run.stateless_submitted
    return counted


def _status_label(run: QuizRun) -> str:
    labels = {
        QuizRun.Status.SCHEDULED: _("Planned"),
        QuizRun.Status.OPEN: _("Running"),
        QuizRun.Status.CLOSED: _("Ended"),
        QuizRun.Status.ARCHIVED: _("Archived"),
    }
    return labels[QuizRun.Status(run.status)]


def _public_url(request: HttpRequest, quiz: Quiz) -> str:
    return request.build_absolute_uri(reverse("quiz", args=[quiz.slug]))


@admin_required
def runs_page(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """POST opens a new run; GET is the tab with the running run and the history."""
    if request.method == "POST":
        return run_open(request, quiz_id)
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    submitted = Count("attempts", filter=Q(attempts__status__in=Attempt.FINISHED))
    runs = list(
        quiz.runs.annotate(submitted=submitted)
        .prefetch_related("revision_rows__revision")
        .order_by("-run_no")
    )
    for run in runs:
        run.submitted = _submitted(run, run.submitted)
    show_archived = request.GET.get("archived") == "1"
    archived = QuizRun.Status.ARCHIVED
    rows = [
        {
            "run": run,
            "status": _status_label(run),
            "limit_minutes": run.attempt_limit_sec // 60 if run.attempt_limit_sec else None,
            "unsent": run_schedule.unsent(run),
            "revisions": ", ".join(
                str(number)
                for number in sorted(row.revision.revision_no for row in run.revision_rows.all())
            ),
        }
        for run in runs
        if show_archived or run.status != archived
    ]
    context = workspace(quiz, "runs") | {
        "rows": rows,
        "comparison": [  # the archive switch hides an archived run here too
            row for row in run_stats.comparison(quiz) if row.run_id in {r["run"].id for r in rows}
        ],
        "running": next((row["run"] for row in rows if row["run"].status == "OPEN"), None),
        "show_archived": show_archived,
        "has_archived": quiz.runs.filter(status=archived).exists(),
        "public_url": _public_url(request, quiz),
    }
    return page(request, "admin/runs.html", context, request.locale)  # type: ignore[attr-defined]


def _refusal(code: str) -> str:
    messages = {
        "start_in_past": _("The start has already passed."),
        "deadline_before_start": _("The deadline must be after the start."),
        "already_planned": _("This quiz already has a running or planned run."),
        "not_planned": _("This run is no longer planned."),
        "deadline_too_soon": _("The deadline must be at least a minute ahead."),
        "not_open": _("This run has ended."),
    }
    return messages.get(code, _("This cannot be done now."))


def _data_initial(values: dict[str, str]) -> dict[str, str]:
    return {
        settings.DATA_PROFILE: values[data_policy.PROFILE],
        settings.RETENTION_PERIOD: values[data_policy.PERIOD],
    }


# Plan fields that are not catalogue settings, placed in a group (ADR-0052)
_PLAN_EXTRA = {
    "access_code": ("participants", "advanced"),
    "generate_code": ("participants", "advanced"),
}


def _plan_page(
    request: HttpRequest, quiz: Quiz, form: RunPlanForm, run: QuizRun | None
) -> HttpResponse:
    """Time fields first; each group collapsed unless it differs from the quiz or was refused."""
    inherited = (
        participants.rules_for_quiz(quiz)
        | _data_initial(data_policy.rules_for_quiz(quiz))
        | results.rules_for_quiz(quiz)
        | rewards.rules_for_quiz(quiz)
    )

    def differs(name: str) -> bool:
        """Chosen unlike the quiz, or named by a refusal; an empty choice follows the quiz."""
        if name in form.refused:
            return True
        current = form.data.get(name) if form.is_bound else form.initial.get(name)
        if name in _PLAN_EXTRA:
            return bool(current) and current not in ("off", "")
        return bool(current) and current != inherited.get(name)

    groups = admin_view.group_fields(
        form, basic=admin_view.is_basic(request), differs=differs, extra=_PLAN_EXTRA
    )
    context = (
        workspace(quiz, "runs")
        | {
            "form": form,
            "planned": run,
            "groups": groups,
            "ungrouped": admin_view.outside_groups(form, extra=_PLAN_EXTRA),
            "collapse": True,
        }
        | _plan_rewards(request, run)
    )
    return page(request, "admin/run_plan.html", context, request.locale)  # type: ignore[attr-defined]


def _plan_rewards(request: HttpRequest, run: QuizRun | None) -> dict[str, Any]:
    if run is None:
        return {}
    locale = request.locale  # type: ignore[attr-defined]
    return {
        "reward_names": [
            rewards.text(rule, run.quiz, locale, "name") for rule in rewards.rules_of(run)
        ],
        "reward_warning": rewards.contact_warning(run),
    }


# Which setting a reward conflict is about, so its group opens (ADR-0052)
_REWARD_FIELDS = {
    rewards.PROFILE: settings.DATA_PROFILE,
    rewards.CONTACT: WINNER_CONTACT,
}


def _reward_refused(form: RunPlanForm, error: rewards.RewardConflict) -> None:
    for key in error.keys:
        if key in _REWARD_FIELDS:
            form.refused.add(_REWARD_FIELDS[key])
        if key == rewards.CONTACT:
            form.refused.add(ASK_EMAIL)
    for line in error.messages():
        form.add_error(None, line)


def _save_new(request: HttpRequest, quiz: Quiz, form: RunPlanForm) -> QuizRun:
    """Raises what `_plan_page` turns into a message."""
    admin_id = str(request.user.pk)
    starts_at = form.cleaned_data["starts_at"]
    deadline_at = form.cleaned_data["deadline_at"]
    if starts_at is None:
        return run_schedule.open_now(
            quiz,
            deadline_at=deadline_at,
            limit_sec=form.limit_seconds(),
            admin_id=admin_id,
            rules=form.rules(),
            data=form.retention(),
            results=form.results(),
            rewards=form.rewards(),
        )
    return run_schedule.plan(
        quiz,
        starts_at=starts_at,
        deadline_at=deadline_at,
        limit_sec=form.limit_seconds(),
        admin_id=admin_id,
        rules=form.rules(),
        data=form.retention(),
        results=form.results(),
        rewards=form.rewards(),
    )


def _apply_code(request: HttpRequest, run: QuizRun, form: RunPlanForm) -> str | None:
    """The code to show once, or None when the form left the code as it was."""
    code = form.code()
    if code is not None:
        access_codes.set_code(run, code, admin_id=str(request.user.pk))
    return code and code.strip().upper()


def _saved(request: HttpRequest, run: QuizRun, code: str | None) -> HttpResponse:
    """A new code is shown by this response only: no redirect, session or message holds it."""
    if code is None:
        return redirect("admin_run", run.id)
    return _show_code(request, run, code)


def _show_code(request: HttpRequest, run: QuizRun, code: str) -> HttpResponse:
    run = QuizRun.objects.select_related("quiz").get(pk=run.pk)
    context = _run_context(request, run) | {"new_code": code}
    return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@not_archived
def run_plan(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method != "POST":
        seconds = settings.attempt_limit_seconds(quiz)
        form = RunPlanForm(
            initial={"limit_minutes": seconds // 60 if seconds else None}
            | participants.rules_for_quiz(quiz)
            | _data_initial(data_policy.rules_for_quiz(quiz))
            | results.rules_for_quiz(quiz)
            | rewards.rules_for_quiz(quiz)
        )
        return _plan_page(request, quiz, form, None)
    form = RunPlanForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():  # a run never opens before its code is in place
                run = _save_new(request, quiz, form)
                code = _apply_code(request, run, form)
            return _saved(request, run, code)
        except run_schedule.ScheduleRefused as error:
            form.add_error(None, _refusal(error.code))
        except data_policy.StatelessConflict as error:
            form.refused.update(error.keys)
            for line in conflict_messages(error.keys):
                form.add_error(None, line)
        except results.ResultConflict as error:
            form.refused.update(error.keys)
            for line in result_messages(error.reasons):
                form.add_error(None, line)
        except rewards.RewardConflict as error:
            _reward_refused(form, error)
        except authoring.NothingPublished:
            form.add_error(None, _("Publish the quiz first."))
        except authoring.RunAlreadyOpen:
            form.add_error(None, _refusal("already_planned"))
        except authoring.RequirementUnmet as error:
            form.add_error(None, " ".join(error.reasons))
    return _plan_page(request, quiz, form, None)


def _planned(run_id: UUID) -> QuizRun:
    return get_object_or_404(
        QuizRun.objects.select_related("quiz", "current_revision"),
        pk=run_id,
        status=QuizRun.Status.SCHEDULED,
    )


@admin_required
def plan_edit(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = _planned(run_id)
    if request.method != "POST":
        seconds = run.attempt_limit_sec
        form = RunPlanForm(
            initial={
                "starts_at": clock.form_value(run.starts_at),
                "deadline_at": clock.form_value(run.deadline_at),
                "limit_minutes": seconds // 60 if seconds else None,
            }
            | participants.rules_of(run)
            | _data_initial(data_policy.of(run))
            | results.of(run)
            | rewards.of(run)
        )
        return _plan_page(request, run.quiz, form, run)
    form = RunPlanForm(request.POST)
    if form.is_valid() and form.cleaned_data["starts_at"] is None:
        form.add_error("starts_at", _("Enter a start. To start now, use Start now."))
    if form.is_valid():
        try:
            with transaction.atomic():
                run_schedule.update_plan(
                    run,
                    starts_at=form.cleaned_data["starts_at"],
                    deadline_at=form.cleaned_data["deadline_at"],
                    limit_sec=form.limit_seconds(),
                    admin_id=str(request.user.pk),
                    rules=form.rules(),
                    data=form.retention(),
                    results=form.results(),
                    # A field "Basic" hides is not sent: the run keeps its value (ADR-0052).
                    rewards=rewards.of(run) | form.rewards(),
                )
                code = _apply_code(request, run, form)
            return _saved(request, run, code)
        except data_policy.StatelessConflict as error:
            form.refused.update(error.keys)
            for line in conflict_messages(error.keys):
                form.add_error(None, line)
        except results.ResultConflict as error:
            form.refused.update(error.keys)
            for line in result_messages(error.reasons):
                form.add_error(None, line)
        except rewards.RewardConflict as error:
            _reward_refused(form, error)
        except run_schedule.ScheduleRefused as error:
            form.add_error(None, _refusal(error.code))
    return _plan_page(request, run.quiz, form, run)


@admin_required
@require_POST
def plan_cancel(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = _planned(run_id)
    run_schedule.cancel_plan(run, admin_id=str(request.user.pk))
    return redirect("admin_run_open", run.quiz_id)


@admin_required
@require_POST
def plan_start(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = _planned(run_id)
    try:
        run_schedule.start_now(run, admin_id=str(request.user.pk))
    except authoring.RequirementUnmet as error:
        problem = " ".join(error.reasons)
    except data_policy.StatelessConflict as error:
        problem = " ".join(conflict_messages(error.keys))
    except rewards.RewardConflict as error:
        problem = " ".join(error.messages())
    except run_schedule.ScheduleRefused as error:
        problem = _refusal(error.code)
    else:
        return redirect("admin_run", run.id)
    context = (
        workspace(run.quiz, "runs", problem)
        | {"form": RunPlanForm(), "planned": run}
        | _plan_rewards(request, run)
    )
    return page(request, "admin/run_plan.html", context, request.locale)  # type: ignore[attr-defined]


def _run_context(request: HttpRequest, run: QuizRun) -> dict[str, Any]:
    run_rules = rewards.rules_of(run)
    return workspace(run.quiz, "runs") | {
        "run": run,
        "is_open": run.status == QuizRun.Status.OPEN,
        "status_label": _status_label(run),
        "unsent": run_schedule.unsent(run),
        "deadline_value": clock.form_value(run.deadline_at),
        "limit_minutes": run.attempt_limit_sec // 60 if run.attempt_limit_sec else None,
        "rules": [
            (settings.CATALOGUE[key].label, settings.CATALOGUE[key].value_labels[value])
            for key, value in participants.rules_of(run).items()
        ],
        "data_rules": [
            (settings.CATALOGUE[name].label, settings.CATALOGUE[name].value_labels[value])
            for name, value in (
                (settings.DATA_PROFILE, data_policy.of(run)[data_policy.PROFILE]),
                (settings.RETENTION_PERIOD, data_policy.of(run)[data_policy.PERIOD]),
            )
        ],
        "result_fields": [
            (
                key,
                settings.CATALOGUE[key].label,
                [
                    (v, settings.CATALOGUE[key].value_labels[v])
                    for v in settings.CATALOGUE[key].choices
                ],
                results.of(run)[key],
            )
            for key in RESULT_DISPLAY_KEYS
        ],
        "result_fixed": [
            (
                settings.CATALOGUE[key].label,
                settings.CATALOGUE[key].value_labels[results.of(run)[key]],
            )
            for key in (OFFICIAL_ATTEMPT, TIE_BREAK_POLICY)
        ],
        "revision_mode": results.revision_mode(run),
        "stats": _stats(run, request.locale),  # type: ignore[attr-defined]
        "admin_board": results.board(run, audience="admin", locale=request.locale),  # type: ignore[attr-defined]
        "public_board_url": reverse("scoreboard", args=[run.quiz.slug, run.id])
        if run.kind == QuizRun.Kind.NORMAL
        else None,
        "can_merge": run.kind == QuizRun.Kind.NORMAL
        and run.revision_rows.values("revision_id").distinct().count() > 1,
        "can_set_results": run.kind != QuizRun.Kind.TEST,
        "period_value": data_policy.of(run)[data_policy.PERIOD],
        "period_choices": [
            (value, settings.CATALOGUE[settings.RETENTION_PERIOD].value_labels[value])
            for value in settings.CATALOGUE[settings.RETENTION_PERIOD].choices
        ],
        "can_set_period": run.kind != QuizRun.Kind.TEST,
        "public_url": _public_url(request, run.quiz),
        "has_code": bool(run.access_code_hash),
        "can_set_code": run.status in (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN),
        "stateless": data_policy.is_stateless(attempts.effective_profile(run)),
        **_attempt_table(request, run),
        "submitted": _submitted(run, run.attempts.filter(status__in=Attempt.FINISHED).count()),
        "reward_count": len(run_rules),
        "has_draw": any(rule.kind == RewardRule.Kind.DRAW for rule in run_rules),
        "contact_warning": rewards.contact_warning(run),
        "walkthrough_url": reverse("walkthrough_page", args=[run.quiz.slug, run.id])
        if walkthrough.available(run)
        else None,
    }


@admin_required
def run_detail(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    return page(request, "admin/run.html", _run_context(request, run), request.locale)  # type: ignore[attr-defined]


def _read_deadline(value: str) -> datetime | None:
    """Raises ValueError for what cannot be used."""
    return clock.parse_local(value) if value else None


def _confirm_earlier(request: HttpRequest, run: QuizRun, value: str) -> HttpResponse:
    """A shorter time takes minutes from people playing now, so the admin sees how many."""
    context = {
        "quiz": run.quiz,
        "message": _("Move the deadline to %(when)s? Attempts in progress: %(count)s.")
        % {"when": clock.shown(clock.parse_local(value)), "count": run_schedule.in_progress(run)},
        "action": reverse("admin_run_deadline", args=[run.id]),
        "cancel": reverse("admin_run", args=[run.id]),
        "hidden": {"deadline_at": value, "confirmed": "1"},
    }
    return page(request, "admin/confirm.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def run_deadline(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    value = request.POST.get("deadline_at", "").strip()
    try:
        deadline = _read_deadline(value)
    except ValueError:
        problem = _("Enter a valid time.")
    else:
        earlier = deadline is not None and (run.deadline_at is None or deadline < run.deadline_at)
        if earlier and not request.POST.get("confirmed"):
            return _confirm_earlier(request, run, value)
        try:
            run_schedule.set_deadline(run, deadline, admin_id=str(request.user.pk))
            return redirect("admin_run", run.id)
        except run_schedule.ScheduleRefused as error:
            problem = _refusal(error.code)
    context = _run_context(request, run) | {"run_error": problem, "deadline_value": value}
    return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def run_period(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    try:
        run_schedule.set_period(
            run, request.POST.get("retention_period", ""), admin_id=str(request.user.pk)
        )
    except run_schedule.ScheduleRefused as error:
        context = _run_context(request, run) | {"run_error": _refusal(error.code)}
        return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]
    return redirect("admin_run", run.id)


@admin_required
@require_POST
def run_scoreboard(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """What the scoreboard shows; the order a run decides by stays as it opened."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    try:
        results.set_display(run, request.POST, admin_id=str(request.user.pk))
    except results.ResultConflict as error:
        context = _run_context(request, run) | {
            "run_error": " ".join(result_messages(error.reasons))
        }
        return page(request, "admin/run.html", context, request.locale, status=409)  # type: ignore[attr-defined]
    return redirect("admin_run", run.id)


def _attempt_table(request: HttpRequest, run: QuizRun) -> dict[str, Any]:
    """Sorted by a query parameter, so a header link works without JavaScript."""
    sort = request.GET.get("sort", "submitted")
    if sort not in participants.ROW_SORTS:
        sort = "submitted"
    descending = request.GET.get("dir") == "desc"
    rows = participants.attempt_rows(run, sort, descending)

    def header(key: str) -> dict[str, str | None]:
        active = key == sort
        flip = "asc" if active and descending else ("desc" if active else "asc")
        return {
            "href": f"?sort={key}&dir={flip}#attempts",
            "aria": ("descending" if descending else "ascending") if active else None,
        }

    return {
        "attempt_rows": rows,
        "attempt_headers": {key: header(key) for key in participants.ROW_SORTS},
        "attempt_durations": any(row.duration_ms is not None for row in rows),
    }


def _stats(run: QuizRun, locale: str) -> dict[str, Any]:
    found = run_stats.of_run(run)
    if locale not in run.quiz.supported_locales:  # questions exist only in the quiz's languages
        locale = run.quiz.default_locale
    bands = found.summary.bands if found.summary else ()
    return {
        "run": found,
        "bands": [
            (f"{index * 10}–{index * 10 + 10} %", count) for index, count in enumerate(bands)
        ],
        "band_top": max(bands, default=0) or 1,
        "questions": [
            (question_label(item.question, locale), item) for item in found.questions or []
        ],
    }


def _merge_refusal(code: str) -> str:
    if code == "max_differs":
        return _("The revisions have different maximum points, so they cannot share one table.")
    return _("The run used only one revision, so there is nothing to merge.")


def _merge_refused(run: QuizRun) -> str | None:
    rows = run.revision_rows.all()
    if rows.values("revision_id").distinct().count() < 2:
        return "one_revision"
    if rows.values("max_score").distinct().count() > 1:
        return "max_differs"
    return None


@admin_required
def run_merge(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """Shows what differs between the run's revisions; merging is a knowing decision (AC-06)."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    if request.method == "POST":
        try:
            results.merge(run, admin_id=str(request.user.pk))
        except results.MergeRefused as error:
            context = _merge_context(run) | {"refused": _merge_refusal(error.code)}
            return page(request, "admin/run_merge.html", context, request.locale, status=409)  # type: ignore[attr-defined]
        return redirect(reverse("admin_run", args=[run.id]) + "#scoreboard")
    refused = _merge_refused(run)
    context = _merge_context(run) | {"refused": _merge_refusal(refused) if refused else None}
    return page(request, "admin/run_merge.html", context, request.locale)  # type: ignore[attr-defined]


def _merge_context(run: QuizRun) -> dict[str, Any]:
    used: list[Any] = []
    for row in run.revision_rows.select_related("revision").order_by("active_from"):
        if not used or used[-1].revision_id != row.revision_id:
            used.append(row)
    pairs = [
        {
            "before": before.revision,
            "after": after.revision,
            "before_max": before.max_score,
            "after_max": after.max_score,
            "diff": revision_diff.compare(
                before.revision.snapshot_json,
                after.revision.snapshot_json,
                revision_diff.locales_of(after.revision.snapshot_json),
            ),
        }
        for before, after in zip(used, used[1:], strict=False)
    ]
    return workspace(run.quiz, "runs") | {"run": run, "pairs": pairs}


@admin_required
@require_POST
def run_unmerge(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun, pk=run_id)
    results.unmerge(run, admin_id=str(request.user.pk))
    return redirect(reverse("admin_run", args=[run.id]) + "#scoreboard")


@admin_required
@require_POST
def run_archive(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun, pk=run_id)
    # A stale page may ask for what has already happened; its result is the same page.
    with contextlib.suppress(run_schedule.ScheduleRefused):
        run_schedule.archive(run, admin_id=str(request.user.pk))
    return redirect("admin_run", run.id)


@admin_required
@require_POST
def run_restore(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun, pk=run_id)
    with contextlib.suppress(run_schedule.ScheduleRefused):
        run_schedule.restore(run, admin_id=str(request.user.pk))
    return redirect("admin_run", run.id)


@admin_required
@require_POST
def walkthrough_hide(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    question = request.POST.get("question", "")
    key = request.POST.get("key", "")
    if not (question and key):
        return HttpResponseBadRequest()
    change = walkthrough.hide_value if request.POST.get("hidden") else walkthrough.show_value
    change(run, question, key, admin_id=str(request.user.pk))
    return redirect("walkthrough_page", run.quiz.slug, run.id)


@admin_required
def run_close(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """The main button can end a run, so GET asks first."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    if request.method == "POST":
        authoring.close_run(run, admin_id=str(request.user.pk))
        return redirect("admin_run", run.id)
    context = {
        "quiz": run.quiz,
        "message": _("End run %(no)s? Participants can no longer submit answers.")
        % {"no": run.run_no},
        "action": reverse("admin_run_close", args=[run.id]),
        "cancel": reverse("admin_run", args=[run.id]),
    }
    return page(request, "admin/confirm.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def quiz_qr(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    buffer = io.BytesIO()
    segno.make(_public_url(request, quiz), error="m").save(buffer, kind="svg", scale=4, border=2)
    return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")


@admin_required
@require_POST
def run_code(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """Set, generate or remove the access code. A new code is shown once, in this response."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    action = request.POST.get("action", "")
    typed = request.POST.get("access_code", "").strip()
    if action == "generate":
        code: str | None = access_codes.generate()
    elif action == "set" and typed:
        code = typed[:64]
    elif action == "remove":
        code = None
    else:
        problem = _("Enter a code.")
        context = _run_context(request, run) | {"run_error": problem}
        return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]
    try:
        access_codes.set_code(run, code, admin_id=str(request.user.pk))
    except access_codes.CodeRefused:
        context = _run_context(request, run) | {"run_error": _refusal("not_open")}
        return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]
    if code is None:
        return redirect("admin_run", run.id)
    return _show_code(request, run, code.strip().upper())
