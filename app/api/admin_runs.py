"""The runs tab, a run's page, ending it, and the quiz's QR code (FR-02)."""

import contextlib
import io
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import segno
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from app.api import admin_view, run_tabs
from app.api.admin_auth import admin_required
from app.api.admin_common import confirm_page, refusal
from app.api.admin_forms import RunPlanForm, conflict_messages, result_messages
from app.api.admin_quizzes import archived_message, not_archived, run_open
from app.api.admin_workspace import workspace
from app.api.inline_name import NameField, render_field, wants_partial
from app.api.rendering import page, question_label
from app.contracts import (
    ASK_EMAIL,
    OFFICIAL_ATTEMPT,
    RESULT_DISPLAY_KEYS,
    TIE_BREAK_POLICY,
    WINNER_CONTACT,
    RetentionProvider,
)
from app.domain import (
    access_codes,
    attempts,
    authoring,
    clock,
    data_policy,
    participants,
    results,
    retention,
    rewards,
    run_schedule,
    run_stats,
    settings,
    walkthrough,
)
from app.domain.models import Attempt, Participant, Quiz, QuizRun
from app.kernel import registry


def _submitted(run: QuizRun, counted: int) -> int:
    """Under "nothing" no attempt row stays, so the run's own count is the number."""
    if data_policy.is_stateless(attempts.effective_profile(run)):
        return run.stateless_submitted
    return counted


def _deletion(run: QuizRun, now: datetime) -> dict[str, Any] | None:
    """What the list of runs and the run page say about when the data go. None for no date."""
    if run.data_deleted_at is not None:
        return {"state": "deleted", "at": run.data_deleted_at}
    at = data_policy.deletion_at(run)
    if at is None:
        return None
    if run.retention_held_at is not None:  # past its date, but no pass deletes it
        return {"state": "held", "at": at}
    return {
        "state": "planned",
        "at": at,
        "soon": data_policy.deletion_soon(run, now),
        "days": data_policy.days_left(run, now),
    }


def _public_url(request: HttpRequest, quiz: Quiz) -> str:
    """The quiz's own address start when it has one, else the address the admin is on."""
    path = reverse("quiz", args=[quiz.slug])
    return quiz.public_origin + path if quiz.public_origin else request.build_absolute_uri(path)


@admin_required
def runs_page(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """POST opens a new run; GET is the tab with the running run and the history."""
    if request.method == "POST":
        return run_open(request, quiz_id)
    return _runs_response(request, get_object_or_404(Quiz, pk=quiz_id))


def _boards(runs: list[QuizRun]) -> list[dict[str, Any]]:
    """The shared boards of the listed runs, newest main run first."""
    mains = [run for run in runs if run.board_main_id is None]
    boards = []
    for main in mains:
        members = sorted(
            (run for run in runs if run.board_main_id == main.id), key=lambda run: run.run_no or 0
        )
        if members:
            joined = sorted([main, *members], key=lambda run: run.run_no or 0)
            boards.append({"main": main, "numbers": ", ".join(str(r.run_no) for r in joined)})
    return boards


def _runs_response(
    request: HttpRequest,
    quiz: Quiz,
    run_error: str | None = None,
    status: int = 200,
    chosen: tuple[str, set[str]] | None = None,
) -> HttpResponse:
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
    now = timezone.now()
    rows = [
        {
            "run": run,
            "status": run_tabs.status_label(run),
            "limit_minutes": run.attempt_limit_sec // 60 if run.attempt_limit_sec else None,
            "unsent": run_schedule.unsent(run),
            "deletion": _deletion(run, now),
            "revisions": ", ".join(
                str(number)
                for number in sorted(row.revision.revision_no for row in run.revision_rows.all())
            ),
        }
        for run in runs
        if show_archived or run.status != archived
    ]
    boards = _boards(runs)
    editing = boards[0]["main"] if boards else None
    for item in rows:
        run = item["run"]
        item["board_main"] = run.board_main_id
        # A run of another shared board stays out of this form: split that board first.
        item["board_locked"] = editing is not None and (
            run.board_main_id not in (None, editing.id)
            or (run.board_main_id is None and run.id != editing.id and run in _mains(boards))
        )
        item["board_chosen"] = (
            run.id in chosen[1]
            if chosen
            else editing is not None and (run.id == editing.id or run.board_main_id == editing.id)
        )
        item["board_is_main"] = (
            str(run.id) == chosen[0] if chosen else editing is not None and run.id == editing.id
        )
    context = workspace(quiz, "runs", run_error) | {
        "boards": boards,
        "can_share": sum(1 for item in rows if not item["board_locked"]) >= 2,
        "rows": rows,
        "comparison": [  # the archive switch hides an archived run here too
            row for row in run_stats.comparison(quiz) if row.run_id in {r["run"].id for r in rows}
        ],
        "running": next((row["run"] for row in rows if row["run"].status == "OPEN"), None),
        "show_archived": show_archived,
        "has_archived": quiz.runs.filter(status=archived).exists(),
        "public_url": _public_url(request, quiz),
    }
    return page(request, "admin/runs.html", context, request.locale, status=status)  # type: ignore[attr-defined]


def _mains(boards: list[dict[str, Any]]) -> list[QuizRun]:
    return [board["main"] for board in boards]


def _share_message(code: str, selected: list[QuizRun], main: QuizRun) -> str:
    """The sentence for a refusal; a run is named by its number."""
    if code == "already_shared":
        other = next((r for r in selected if r.board_main_id not in (None, main.id)), None)
        if other is None:  # a chosen run is itself the main run of another board
            other = next((r for r in selected if r.board_members.exists()), selected[0])
        return _("Run %(no)s is already on the shared scoreboard of another run.") % {
            "no": other.run_no
        }
    if code == "main_is_member":
        return _("Run %(no)s is part of the shared scoreboard of another run.") % {
            "no": main.run_no
        }
    messages = {
        "too_few": _("Choose at least two runs."),
        "other_quiz": _("A run belongs to another quiz."),
        "test_run": _("A test run cannot be on a shared scoreboard."),
    }
    return messages.get(code, _("This cannot be done now."))


@admin_required
@require_POST
@not_archived
def board_share(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """One public scoreboard for the main run that shows the ticked runs too (ADR-0065)."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    main_id = request.POST.get("main", "")
    ticked = set(request.POST.getlist("runs"))
    chosen = (main_id, ticked | {main_id})
    main = _run_by_id(main_id)
    if main is None:
        return _runs_response(request, quiz, _("Choose the main run."), status=400, chosen=chosen)
    if main.quiz_id != quiz.id:
        message = _share_message("other_quiz", [], main)
        return _runs_response(request, quiz, message, status=409, chosen=chosen)
    found = [_run_by_id(value) for value in sorted(ticked - {main_id})]
    if any(run is None for run in found):
        message = _("The chosen runs have changed. Reload the page.")
        return _runs_response(request, quiz, message, status=400, chosen=chosen)
    selected = [run for run in found if run is not None]
    if request.POST.get("archived") != "1":
        # Archived runs are not on the list, so saving it must not unlink the ones already there.
        hidden = main.board_members.filter(status=QuizRun.Status.ARCHIVED)
        selected += [run for run in hidden if run not in selected]
    try:
        results.share_board(main, selected, admin_id=str(request.user.pk))
    except results.ShareRefused as refused:
        message = _share_message(refused.code, selected, main)
        return _runs_response(request, quiz, message, status=409, chosen=chosen)
    except authoring.QuizArchived:
        return _runs_response(request, quiz, archived_message(), status=409, chosen=chosen)
    return redirect("admin_run_open", quiz.id)


def _run_by_id(value: str) -> QuizRun | None:
    try:
        return QuizRun.all_kinds.select_related("quiz").filter(pk=UUID(value)).first()
    except ValueError:
        return None


@admin_required
@require_POST
def board_split(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    try:
        results.split_board(run, admin_id=str(request.user.pk))
    except authoring.QuizArchived:
        return _tab_page(request, run, "scoreboard", {"run_error": archived_message()}, status=409)
    return redirect("admin_run_open", run.quiz_id)


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
    # A refusal of the rules is 409, a field that did not validate 400; both keep the page.
    status = 200 if not form.is_bound else 409 if form.non_field_errors() else 400
    return page(request, "admin/run_plan.html", context, request.locale, status=status)  # type: ignore[attr-defined]


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
    return _tab_page(request, run, "settings", {"new_code": code})


@admin_required
@not_archived
def run_plan(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if authoring.latest_published(quiz) is None:  # nothing a run could take: publish first
        status = 409 if request.method == "POST" else 200
        context = workspace(quiz, "runs") | {"unpublished": True, "planned": None}
        return page(request, "admin/run_plan.html", context, request.locale, status=status)  # type: ignore[attr-defined]
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
            form.add_error(None, refusal(error.code))
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
            form.add_error(None, refusal("already_planned"))
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
            form.add_error(None, refusal(error.code))
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
        problem = refusal(error.code)
    else:
        return redirect("admin_run", run.id)
    context = (
        workspace(run.quiz, "runs", problem)
        | {"form": RunPlanForm(), "planned": run}
        | _plan_rewards(request, run)
    )
    return page(request, "admin/run_plan.html", context, request.locale, status=409)  # type: ignore[attr-defined]


def _has_deletion_records(run: QuizRun) -> bool:
    return bool(cast(RetentionProvider, registry.get("retention", "local")).for_run(str(run.pk)))


def _header_context(request: HttpRequest, run: QuizRun, tab: str) -> dict[str, Any]:
    """The quiz header, the run header and its tab bar, the same on every tab (ADR-0068)."""
    basic = admin_view.is_basic(request)
    return (
        workspace(run.quiz, "runs")
        | run_tabs.header(run, tab, basic=basic)
        | {"is_open": run.status == QuizRun.Status.OPEN}
    )


def _overview(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    return {
        "unsent": run_schedule.unsent(run),
        "deadline_value": clock.form_value(run.deadline_at),
        "limit_minutes": run.attempt_limit_sec // 60 if run.attempt_limit_sec else None,
        "deletion": _deletion(run, timezone.now()),
        "has_deletion_records": _has_deletion_records(run),
        "public_url": _public_url(request, run.quiz),
        "submitted": _submitted(run, run.attempts.filter(status__in=Attempt.FINISHED).count()),
        "contact_warning": rewards.contact_warning(run),
    }


def _attempts(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    return {
        "rules": [
            (settings.CATALOGUE[key].label, settings.CATALOGUE[key].value_labels[value])
            for key, value in participants.rules_of(run).items()
        ],
        "stateless": data_policy.is_stateless(attempts.effective_profile(run)),
        **_attempt_table(request, run, name_field),
        "walkthrough_url": reverse("walkthrough_page", args=[run.quiz.slug, run.id])
        if walkthrough.available(run)
        else None,
    }


def _scoreboard(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    return {
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
        "admin_board": results.board(run, audience="admin", locale=request.locale),  # type: ignore[attr-defined]
        "board_numbers": ", ".join(map(str, results.shared_numbers(run))),
        "board_main_run": run.board_main if run.board_main_id else None,
        "public_board_url": reverse("scoreboard", args=[run.quiz.slug, run.id])
        if run.kind == QuizRun.Kind.NORMAL
        else None,
        "can_set_results": run.kind != QuizRun.Kind.TEST,
    }


def _statistics(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    return {
        "stats": _stats(run, request.locale),  # type: ignore[attr-defined]
        "stateless": data_policy.is_stateless(attempts.effective_profile(run)),
    }


def _export(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    return {}


def _settings(request: HttpRequest, run: QuizRun, name_field: NameField | None) -> dict[str, Any]:
    basic = admin_view.is_basic(request)
    return {
        "data_rules": [
            (settings.CATALOGUE[name].label, settings.CATALOGUE[name].value_labels[value])
            for name, value in (
                (settings.DATA_PROFILE, data_policy.of(run)[data_policy.PROFILE]),
                (settings.RETENTION_PERIOD, data_policy.of(run)[data_policy.PERIOD]),
            )
        ],
        "period_value": data_policy.of(run)[data_policy.PERIOD],
        "period_choices": [
            (value, settings.CATALOGUE[settings.RETENTION_PERIOD].value_labels[value])
            for value in settings.CATALOGUE[settings.RETENTION_PERIOD].choices
        ],
        "can_set_period": run.kind != QuizRun.Kind.TEST and run.data_deleted_at is None,
        "can_delete_data": retention.deletable(run),
        "deletion": _deletion(run, timezone.now()),
        "has_code": bool(run.access_code_hash),
        "can_set_code": run.status in (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN),
        "empty_in_basic": run_tabs.settings_empty(run, basic=basic),
        "access_section": not basic or bool(run.access_code_hash),
        "data_section": not basic,
    }


TabContext = Callable[[HttpRequest, QuizRun, NameField | None], dict[str, Any]]
# Each tab computes only what it shows: no statistics or scoreboard on the Overview.
TAB_TEMPLATES: dict[str, tuple[str, TabContext]] = {
    "overview": ("admin/run.html", _overview),
    "attempts": ("admin/run_attempts.html", _attempts),
    "scoreboard": ("admin/run_scoreboard.html", _scoreboard),
    "statistics": ("admin/run_statistics.html", _statistics),
    "export": ("admin/run_export.html", _export),
    "settings": ("admin/run_settings.html", _settings),
}


def _tab_page(
    request: HttpRequest,
    run: QuizRun,
    tab: str,
    extra: dict[str, Any] | None = None,
    *,
    status: int = 200,
    name_field: NameField | None = None,
) -> HttpResponse:
    template, tab_context = TAB_TEMPLATES[tab]
    context = (
        _header_context(request, run, tab) | tab_context(request, run, name_field) | (extra or {})
    )
    return page(request, template, context, request.locale, status=status)  # type: ignore[attr-defined]


def _tab_view(tab: str) -> Callable[[HttpRequest, UUID], HttpResponse]:
    @admin_required
    @require_safe
    def view(request: HttpRequest, run_id: UUID) -> HttpResponse:
        run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
        return _tab_page(request, run, tab)

    view.__name__ = view.__qualname__ = f"run_{tab}"
    return view


run_detail = _tab_view("overview")
run_attempts = _tab_view("attempts")
run_scoreboard_page = _tab_view("scoreboard")
run_statistics = _tab_view("statistics")
run_export = _tab_view("export")
run_settings = _tab_view("settings")


@admin_required
@require_http_methods(["GET", "POST"])
def participant_name(request: HttpRequest, run_id: UUID, participant_id: UUID) -> HttpResponse:
    """An admin renames a nickname for the scoreboard (AC-161); the rules of the run hold."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    who = get_object_or_404(Participant, pk=participant_id, run=run)
    if request.method == "GET":
        editing = request.GET.get("edit") == "1"
        field = _nick_field(run, who.pk, who.display_name, editing=editing)
        if not wants_partial(request):
            return redirect(field.edit_page if editing else field.back_page)
        return render_field(request, field)
    typed = request.POST.get("name", "")
    try:
        participants.rename(who, typed, admin_id=str(request.user.pk))
    except authoring.QuizArchived:
        return _tab_page(request, run, "attempts", {"run_error": archived_message()}, status=409)
    except participants.NameRefused as refused:
        messages = {
            "empty": _("The name cannot be empty."),
            "too_long": _("A name has at most %(count)s characters.")
            % {"count": participants.NAME_LENGTH},
            "taken": _("Another participant already has this name."),
        }
        field = _nick_field(run, who.pk, typed, editing=True, error=messages[refused.code])
        if wants_partial(request):
            return render_field(request, field, status=400)
        return _tab_page(request, run, "attempts", status=400, name_field=field)
    if wants_partial(request):
        response = render_field(request, _nick_field(run, who.pk, who.display_name, saved=True))
        if who.attempts.filter(status__in=Attempt.FINISHED).count() > 1:
            response["HX-Refresh"] = "true"  # the other rows of this participant show the name too
        return response
    return redirect(_nick_field(run, who.pk, who.display_name).back_page)


def _read_deadline(value: str) -> datetime | None:
    """Raises ValueError for what cannot be used."""
    return clock.parse_local(value) if value else None


def _confirm_earlier(request: HttpRequest, run: QuizRun, value: str) -> HttpResponse:
    """A shorter time takes minutes from people playing now, so the admin sees how many."""
    return confirm_page(
        request,
        quiz=run.quiz,
        message=_("Move the deadline to %(when)s? Attempts in progress: %(count)s.")
        % {"when": clock.shown(clock.parse_local(value)), "count": run_schedule.in_progress(run)},
        action=reverse("admin_run_deadline", args=[run.id]),
        cancel=reverse("admin_run", args=[run.id]),
        hidden={"deadline_at": value, "confirmed": "1"},
    )


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
            problem = refusal(error.code)
    return _tab_page(request, run, "overview", {"run_error": problem, "deadline_value": value})


def _confirm_period(request: HttpRequest, run: QuizRun, period: str) -> HttpResponse:
    """A period already over means the next pass deletes the data, so the admin says so first."""
    return confirm_page(
        request,
        quiz=run.quiz,
        message=_(
            "With this period the date of deletion has already passed, so the data of run "
            "%(no)s will be deleted on the next hourly pass. This cannot be undone."
        )
        % {"no": run.run_no},
        action=reverse("admin_run_period", args=[run.id]),
        cancel=reverse("admin_run_settings", args=[run.id]),
        hidden={"retention_period": period},
    )


@admin_required
@require_POST
def run_period(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    period = request.POST.get("retention_period", "")
    try:
        run_schedule.set_period(
            run,
            period,
            admin_id=str(request.user.pk),
            confirmed=request.POST.get("confirm") == "1",
        )
    except run_schedule.ScheduleRefused as error:
        return _tab_page(request, run, "settings", {"run_error": refusal(error.code)})
    except run_schedule.PeriodNeedsConfirmation:
        return _confirm_period(request, run, period)
    return redirect("admin_run_settings", run.id)


@admin_required
@require_POST
def run_scoreboard_settings(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """What the scoreboard shows; the order a run decides by stays as it opened."""
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    try:
        results.set_display(run, request.POST, admin_id=str(request.user.pk))
    except authoring.QuizArchived:
        return _tab_page(request, run, "scoreboard", {"run_error": archived_message()}, status=409)
    except results.ResultConflict as error:
        problem = " ".join(result_messages(error.reasons))
        return _tab_page(request, run, "scoreboard", {"run_error": problem}, status=409)
    return redirect("admin_run_scoreboard", run.id)


def _nick_field(
    run: QuizRun,
    participant_id: UUID,
    name: str,
    *,
    editing: bool = False,
    error: str = "",
    saved: bool = False,
) -> NameField:
    """The nickname in a row of the table of attempts (AC-161)."""
    host = reverse("admin_run_attempts", args=[run.id])
    name_url = reverse("admin_participant_name", args=[run.id, participant_id])
    return NameField(
        label=_("Name"),
        field="name",
        key=str(participant_id),
        value=name,
        save_url=name_url,
        edit_url=f"{name_url}?edit=1",
        view_url=name_url,
        edit_page=f"{host}?edit={participant_id}",
        back_page=host,
        max_length=participants.NAME_LENGTH,
        editing=editing,
        error=error,
        saved=saved,
        placeholder=_("no name"),
    )


def _attempt_table(
    request: HttpRequest, run: QuizRun, name_field: NameField | None = None
) -> dict[str, Any]:
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
            "href": f"?sort={key}&dir={flip}",
            "aria": ("descending" if descending else "ascending") if active else None,
        }

    asked = request.GET.get("edit", "") if request.method == "GET" else ""
    # One pencil for a participant even when the table has several of their attempts.
    fields: list[NameField | None] = []
    seen: set[UUID] = set()
    for row in rows:
        if row.participant_id is None or row.participant_id in seen:
            fields.append(None)
            continue
        seen.add(row.participant_id)
        key = str(row.participant_id)
        fields.append(
            name_field
            if name_field is not None and name_field.key == key
            else _nick_field(run, row.participant_id, row.name, editing=asked == key)
        )
    return {
        "attempt_rows": rows,
        "name_fields": fields,
        "attempt_headers": {key: header(key) for key in participants.ROW_SORTS},
        "attempt_durations": any(row.duration_ms is not None for row in rows),
        "attempt_passes": results.pass_mark(run) is not None,
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
    return confirm_page(
        request,
        quiz=run.quiz,
        message=_("End run %(no)s? Participants can no longer submit answers.")
        % {"no": run.run_no},
        action=reverse("admin_run_close", args=[run.id]),
        cancel=reverse("admin_run", args=[run.id]),
    )


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
        return _tab_page(request, run, "settings", {"run_error": _("Enter a code.")})
    try:
        access_codes.set_code(run, code, admin_id=str(request.user.pk))
    except authoring.QuizArchived:
        return _tab_page(request, run, "settings", {"run_error": archived_message()}, status=409)
    except access_codes.CodeRefused:
        return _tab_page(request, run, "settings", {"run_error": refusal("not_open")})
    if code is None:
        return redirect("admin_run_settings", run.id)
    return _show_code(request, run, code.strip().upper())
