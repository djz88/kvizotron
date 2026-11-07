"""The runs tab, a run's page, ending it, and the quiz's QR code (FR-02)."""

import io
from uuid import UUID

import segno
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.admin_quizzes import run_open
from app.api.admin_workspace import workspace
from app.api.rendering import page
from app.domain import authoring, walkthrough
from app.domain.models import Attempt, Quiz, QuizRun


def _public_url(request: HttpRequest, quiz: Quiz) -> str:
    return request.build_absolute_uri(reverse("quiz", args=[quiz.slug]))


@admin_required
def runs_page(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """POST opens a new run; GET is the tab with the running run and the history."""
    if request.method == "POST":
        return run_open(request, quiz_id)
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    submitted = Count("attempts", filter=Q(attempts__status__in=Attempt.FINISHED))
    runs = quiz.runs.annotate(submitted=submitted).prefetch_related("revision_rows__revision")
    rows = [
        {
            "run": run,
            "revisions": ", ".join(
                str(number)
                for number in sorted(row.revision.revision_no for row in run.revision_rows.all())
            ),
        }
        for run in runs.order_by("-run_no")
    ]
    context = workspace(quiz, "runs") | {
        "rows": rows,
        "running": next((row["run"] for row in rows if row["run"].status == "OPEN"), None),
        "public_url": _public_url(request, quiz),
    }
    return page(request, "admin/runs.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def run_detail(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    context = workspace(run.quiz, "runs") | {
        "run": run,
        "is_open": run.status == QuizRun.Status.OPEN,
        "public_url": _public_url(request, run.quiz),
        "submitted": run.attempts.filter(status__in=Attempt.FINISHED).count(),
        "walkthrough_url": reverse("walkthrough_page", args=[run.quiz.slug, run.id])
        if walkthrough.available(run)
        else None,
    }
    return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]


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
