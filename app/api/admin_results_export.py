"""Results export: the page that starts a job, the list of jobs and the downloads (FR-42, D2).

The provider keeps jobs and files; `export_runner` writes them in the background. A file is sent
only to the admin who asked for it, only while the job is done and not expired.
"""

import mimetypes
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.db import transaction
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from app.api import admin_common, export_runner
from app.api.admin_auth import admin_required
from app.api.admin_runs import _status_label
from app.api.admin_workspace import workspace
from app.api.rendering import page
from app.contracts import ExportJobGone, ExportJobView, ResultsExporterProvider
from app.domain import data_policy, results_export, settings
from app.domain.models import Quiz, QuizRun

ACTIVE = ("queued", "running")


def _provider() -> ResultsExporterProvider:
    exporter = export_runner.provider()
    if exporter is None:
        raise Http404
    return exporter


def _file_labels() -> dict[str, str]:
    return {
        "attempts": _("Attempts"),
        "participants": _("Participants"),
        "questions": _("Question statistics"),
        "answers": _("Answers"),
        "entitlements": _("Reward entitlements"),
        "draws": _("Draw history"),
    }


def _status_labels() -> dict[str, str]:
    return {
        "queued": _("Waiting"),
        "running": _("Being prepared"),
        "done": _("Ready"),
        "failed": _("Failed"),
        "interrupted": _("Interrupted"),
    }


def _chosen(request: HttpRequest) -> tuple[Quiz, list[QuizRun], bool]:
    """`quiz` and `runs` from the address. `runs` may repeat or hold ids split by commas."""
    try:
        quiz_id = UUID(request.GET.get("quiz", ""))
    except ValueError as exc:
        raise Http404 from exc
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    run_ids = [part for value in request.GET.getlist("runs") for part in value.split(",") if part]
    try:
        runs = results_export.runs_for(quiz, run_ids or None)
    except QuizRun.DoesNotExist as exc:
        raise Http404 from exc
    return quiz, runs, not run_ids


def _jobs_context(request: HttpRequest) -> dict[str, Any]:
    export_runner.kick()  # a slot may have freed since the last job ended
    jobs: list[ExportJobView] = list(_provider().jobs(admin_common.admin_id(request)))
    return {
        "jobs": jobs,
        "jobs_active": any(job.status in ACTIVE for job in jobs),
        "active_statuses": ACTIVE,
        "job_status": _status_labels(),
    }


def _page(
    request: HttpRequest,
    quiz: Quiz,
    runs: list[QuizRun],
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    profile = settings.CATALOGUE[settings.DATA_PROFILE]
    labels = _file_labels()
    context = workspace(quiz, "runs") | {
        "runs": [
            {
                "run": run,
                "status": _status_label(run),
                "profile": profile.value_labels[data_policy.of(run)[data_policy.PROFILE]],
            }
            for run in runs
        ],
        "files": [
            {
                "name": name,
                "label": labels[name],
                "count": count,
                "personal": name in results_export.PERSONAL,
            }
            for name, count in results_export.offered(runs).items()
        ],
        "run_total": len(runs),
        "has_photos": results_export.has_photos(runs),
        "error": error,
        # A refused form comes back as the admin left it; a fresh one has every file and photos.
        "chosen": {
            "files": request.POST.getlist("files"),
            "photos": request.POST.get("photos") == "on",
            "bundle": request.POST.get("bundle", "zip"),
        }
        if request.method == "POST"
        else {"files": list(results_export.FILES), "photos": True, "bundle": "zip"},
        **_jobs_context(request),
    }
    return page(
        request,
        "admin/results_export.html",
        context,
        admin_common.locale_of(request),
        status=status,
    )


def _with_photos(request: HttpRequest, runs: list[QuizRun]) -> bool:
    """Photos go only into a ZIP that has the answers file, which names them."""
    return (
        request.POST.get("bundle") == "zip"
        and "answers" in request.POST.getlist("files")
        and request.POST.get("photos") == "on"
        and results_export.has_photos(runs)
    )


def _refusal(request: HttpRequest, runs: list[QuizRun]) -> str | None:
    files = request.POST.getlist("files")
    offered = results_export.offered(runs)
    if not files:
        return _("Choose at least one file.")
    if any(name not in offered for name in files):
        return _("One of the chosen files cannot be exported from these runs.")
    if request.POST.get("bundle") not in ("zip", "separate"):
        return _("Choose how to download the files.")
    personal = results_export.PERSONAL & set(files) or _with_photos(request, runs)
    if personal and request.POST.get("personal_ok") != "on":
        return _("The export contains personal data. Confirm it to continue.")
    return None


@admin_required
@require_http_methods(["GET", "POST"])
def new(request: HttpRequest) -> HttpResponse:
    quiz, runs, all_runs = _chosen(request)
    if request.method != "POST":
        return _page(request, quiz, runs)
    refusal = _refusal(request, runs)
    if refusal:
        return _page(request, quiz, runs, refusal, status=400)
    files = [name for name in results_export.FILES if name in request.POST.getlist("files")]
    bundle = request.POST["bundle"]
    choices = {
        "quiz": str(quiz.pk),
        "runs": [str(run.pk) for run in runs],
        "all_runs": all_runs,
        "files": files,
        "photos": _with_photos(request, runs),
        "bundle": bundle,
        "locale": admin_common.locale_of(request),
        "name": results_export.file_name(quiz, runs, all_runs, timezone.now()),
    }
    admin_id = admin_common.admin_id(request)
    with transaction.atomic():  # no job without its audit event
        job_id = _provider().create(admin_id, choices)
        results_export.record_created(job_id, admin_id, choices)
    export_runner.kick()  # after the commit, so the worker sees the job
    return redirect(f"{request.get_full_path()}#export-jobs")


@admin_required
@require_GET
def jobs(request: HttpRequest) -> HttpResponse:
    """The list of jobs alone, for the page to poll while one is still waiting or running."""
    translation.activate(admin_common.locale_of(request))
    return render(request, "admin/_export_jobs.html", _jobs_context(request))


def _page_of(choices: Any) -> str:
    query = {"quiz": choices.get("quiz", "")}
    if not choices.get("all_runs"):
        query["runs"] = ",".join(choices.get("runs") or [])
    return f"{reverse('results_export_new')}?{urlencode(query)}#export-jobs"


@admin_required
@require_POST
def restart(request: HttpRequest, job_id: UUID) -> HttpResponse:
    exporter = _provider()
    admin_id = admin_common.admin_id(request)
    try:
        new_id = exporter.restart(str(job_id), admin_id)
        choices = exporter.job(new_id, admin_id).choices
    except ExportJobGone as exc:
        raise Http404 from exc
    export_runner.kick()
    return redirect(_page_of(choices))


@admin_required
@require_GET
def download(request: HttpRequest, job_id: UUID, name: str) -> HttpResponse:
    admin_id = admin_common.admin_id(request)
    try:
        path = _provider().path(str(job_id), admin_id, name)
    except ExportJobGone as exc:
        raise Http404 from exc
    try:
        handle = open(path, "rb")  # noqa: SIM115 - FileResponse closes it
    except FileNotFoundError as exc:
        raise Http404 from exc
    results_export.record_downloaded(str(job_id), admin_id, name)
    content_type = (
        "text/csv; charset=utf-8"
        if name.endswith(".csv")
        else mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    response = FileResponse(handle, as_attachment=True, filename=name, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    return response
