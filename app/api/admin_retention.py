"""Deletion in the administration (D3): the history, held runs, "delete now" and erasure.

An address typed here arrives only in a POST body, and any response that can show one is not
cached.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Any, cast
from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.admin_common import confirm_page, refusal
from app.api.admin_runs import _run_context
from app.api.admin_workspace import quiz_title
from app.api.rendering import page
from app.contracts import RetentionProvider, RetentionRecord
from app.domain import data_policy, heartbeat, retention, settings
from app.domain.models import Quiz, QuizRun
from app.kernel import registry

logger = logging.getLogger(__name__)

_PAGE_SIZE = 200
_LAST_PAGE = 10**9  # keeps the offset within what the database can take


def _no_store(response: HttpResponse) -> HttpResponse:
    """Not the public helper: its `no-referrer` makes a browser fail the CSRF check of a form."""
    response["X-Robots-Tag"] = "noindex"
    response["Cache-Control"] = "private, no-store"
    return response


def _trail() -> RetentionProvider:
    return cast(RetentionProvider, registry.get("retention", "local"))


def _admin_logins(records: Iterable[RetentionRecord]) -> dict[str, str]:
    ids = {record.admin_id for record in records if record.admin_id}
    found = get_user_model().objects.filter(pk__in=ids)
    return {str(user.pk): user.get_username() for user in found}


def _who(record: RetentionRecord, logins: dict[str, str]) -> str:
    if record.admin_id is None:
        return _("automatic")
    return logins.get(record.admin_id, _("a deleted admin"))


def _counts(counts: dict[str, int]) -> list[tuple[str, int]]:
    labels = (
        ("attempts", _("Attempts")),
        ("answers", _("Answers")),
        ("participants", _("Participants")),
        ("entitlements", _("Reward claims")),
        ("hidden_values", _("Hidden answers")),
        ("photos", _("Photos")),
    )
    return [(label, counts.get(key, 0)) for key, label in labels]


def _history_rows(records: Sequence[RetentionRecord]) -> list[dict[str, Any]]:
    triggers = {
        retention.AUTOMATIC: _("Automatic"),
        retention.MANUAL: _("Manual"),
        retention.ERASURE: _("Erasure"),
    }
    periods = settings.CATALOGUE[settings.RETENTION_PERIOD].value_labels
    logins = _admin_logins(records)
    wanted = {record.run_id for record in records}
    runs = {
        str(run.pk): run for run in QuizRun.all_kinds.filter(pk__in=wanted).select_related("quiz")
    }
    return [
        {
            "record": record,
            "trigger": triggers.get(record.trigger, record.trigger),
            "who": _who(record, logins),
            "period": periods.get(record.policy, record.policy),
            "counts": _counts(dict(record.counts)),
            "run": runs.get(record.run_id),
            "quiz_title": quiz_title(runs[record.run_id].quiz) if record.run_id in runs else "",
            "linked": record.run_id in runs and runs[record.run_id].kind == QuizRun.Kind.NORMAL,
        }
        for record in records
    ]


def _page_number(raw: str) -> int:
    """Anything unusable is the first page, also a number too large for the database."""
    try:
        number = int(raw)
    except ValueError:
        return 1
    return number if 1 <= number <= _LAST_PAGE else 1


def _run_filter(raw: str) -> str | None:
    """Something that is no id filters nothing."""
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def _history_page(number: int) -> tuple[int, Sequence[RetentionRecord], bool]:
    """The page really shown, its records and whether older ones follow it."""
    trail = _trail()
    records = trail.history(limit=_PAGE_SIZE + 1, offset=(number - 1) * _PAGE_SIZE)
    if number > 1 and not records:
        number = 1
        records = trail.history(limit=_PAGE_SIZE + 1)
    return number, records[:_PAGE_SIZE], len(records) > _PAGE_SIZE


def _history_context(number: int = 1, run_id: str | None = None) -> dict[str, Any]:
    if run_id is not None:
        records = _trail().for_run(run_id)
        shown, has_next = 1, False
    else:
        shown, records, has_next = _history_page(number)
    return {
        "held": [
            {
                "run": run,
                "quiz_title": quiz_title(run.quiz),
                "due": data_policy.deletion_at(run),
            }
            for run in retention.held_runs()
        ],
        "rows": _history_rows(records),
        "page_number": shown,
        "has_next": has_next,
        "filtered": run_id is not None,
        "last_pass": heartbeat.read_pass(),
    }


@admin_required
def history(request: HttpRequest) -> HttpResponse:
    context = _history_context(
        _page_number(request.GET.get("page", "1")), _run_filter(request.GET.get("run", ""))
    )
    return page(request, "admin/retention.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def held(request: HttpRequest) -> HttpResponse:
    """Only the runs the page listed: a run held after it was shown stays held."""
    posted = _chosen_ids(request.POST.getlist("run"))
    if posted is None:
        problem = _("The list of runs is not valid. Reload the page.")
        context = _history_context() | {"held_error": problem}
        return page(request, "admin/retention.html", context, request.locale)  # type: ignore[attr-defined]
    wanted = sorted(posted)
    if request.POST.get("confirm") == "1":
        retention.release_held(wanted, admin_id=str(request.user.pk))
        return redirect("retention_history")
    still_held = [str(run.pk) for run in retention.held_runs() if str(run.pk) in posted]
    if not still_held:
        return redirect("retention_history")
    return confirm_page(
        request,
        message=_(
            "The data of the runs waiting for confirmation (%(count)s) will be deleted on the "
            "next hourly pass. This cannot be undone."
        )
        % {"count": len(still_held)},
        action=reverse("retention_held"),
        cancel=reverse("retention_history"),
        repeated=[("run", run_id) for run_id in still_held],
    )


@admin_required
@require_POST
def verify(request: HttpRequest) -> HttpResponse:
    """Whether and when an address was erased, and by whom. The address is not shown back."""
    typed = request.POST.get("email", "").strip()
    context = _history_context()
    if not typed:
        context["verify_error"] = _("Enter an e-mail address.")
    else:
        records = retention.erased_records(typed)
        logins = _admin_logins(records)
        context["verified"] = [
            {"at": record.executed_at, "who": _who(record, logins)} for record in records
        ]
        context["verify_done"] = True
    return _no_store(page(request, "admin/retention.html", context, request.locale))  # type: ignore[attr-defined]


@admin_required
@require_POST
def delete_data(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    if run.data_deleted_at is not None:  # a stale page; its result is the same page
        return redirect("admin_run", run.id)
    if not retention.deletable(run):
        return _run_page_with(request, run, refusal("not_ended"))
    if request.POST.get("confirm") != "1":
        return _confirm_delete(request, run)
    try:
        retention.delete_now(run, admin_id=str(request.user.pk))
    except retention.Refused as error:
        return _run_page_with(request, run, refusal(error.code))
    except Exception as exc:  # the type only: a message could carry a personal value
        logger.error("Run %s: data were not deleted: %s", run.pk, type(exc).__name__)
        problem = _(
            "Deleting the data could not be finished. Try again; the hourly pass also resumes it."
        )
        return _run_page_with(request, run, problem)
    return redirect("admin_run", run.id)


def _run_page_with(request: HttpRequest, run: QuizRun, problem: str) -> HttpResponse:
    context = _run_context(request, run) | {"run_error": problem}
    return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]


def _confirm_delete(request: HttpRequest, run: QuizRun) -> HttpResponse:
    return confirm_page(
        request,
        quiz=run.quiz,
        message=_(
            "Delete the data of run %(no)s now? Its attempts, answers, photos, participants and "
            "reward claims will be deleted, and so will prepared export files that include this "
            "run, including an export of all runs of the quiz. The run itself, its revisions, "
            "reward rules, draw history with pseudonyms and anonymous statistics stay. "
            "This cannot be undone."
        )
        % {"no": run.run_no},
        action=reverse("admin_run_delete_data", args=[run.id]),
        cancel=reverse("admin_run", args=[run.id]),
    )


def _search(email: str, name: str) -> list[retention.Found]:
    return retention.search_email(email) if email else retention.search_name(name)


def _erasure_rows(found: Sequence[retention.Found]) -> list[dict[str, Any]]:
    quizzes = Quiz.objects.in_bulk({row.quiz_id for row in found})
    return [{"found": row, "quiz_title": quiz_title(quizzes[UUID(row.quiz_id)])} for row in found]


def _chosen_ids(values: Sequence[str]) -> set[str] | None:
    """None for anything that is not an id: filtering by it would raise."""
    try:
        return {str(UUID(value)) for value in values}
    except ValueError:
        return None


def _erasure_page(request: HttpRequest, email: str, name: str, **extra: Any) -> HttpResponse:
    context = {"email": email, "name": name} | extra
    return _no_store(page(request, "admin/erasure.html", context, request.locale))  # type: ignore[attr-defined]


def _results(request: HttpRequest, email: str, name: str, **extra: Any) -> HttpResponse:
    rows = _erasure_rows(_search(email, name))
    return _erasure_page(request, email, name, rows=rows, searched=True, **extra)


def _erase(request: HttpRequest, email: str, name: str) -> HttpResponse:
    """Only what this search finds: a forged id must not get this address's fingerprint."""
    wanted = _chosen_ids(request.POST.getlist("participant"))
    chosen = [row for row in _search(email, name) if wanted and row.participant_id in wanted]
    if not chosen:
        return _results(request, email, name, error=_("Select at least one row."))
    if request.POST.get("confirm") != "1":
        return _erasure_page(request, email, name, confirming=_erasure_rows(chosen))
    ids = [row.participant_id for row in chosen]
    try:
        retention.erase(ids, admin_id=str(request.user.pk), email=email or None)
    except Exception as exc:  # the type only: a message could carry a personal value
        logger.error("Erasure was not finished: %s", type(exc).__name__)
        problem = _(
            "The erasure is incomplete: an export file could not be removed. You can repeat it."
        )
        return _results(request, email, name, error=problem, ticked=set(ids))
    return redirect("retention_history")


@admin_required
def erasure(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return _erasure_page(request, "", "")
    email = request.POST.get("email", "").strip()
    name = request.POST.get("name", "").strip() if not email else ""
    if request.POST.get("action") == "erase":
        return _erase(request, email, name)
    if not email and not name:
        return _erasure_page(request, "", "", error=_("Enter an e-mail address or a nickname."))
    return _results(request, email, name)
