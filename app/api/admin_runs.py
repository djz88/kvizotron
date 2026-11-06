"""A round's page, closing it, and the quiz's QR code (FR-02)."""

import io
from uuid import UUID

import segno
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.rendering import page
from app.domain import authoring
from app.domain.models import Attempt, Quiz, QuizRun


def _public_url(request: HttpRequest, quiz: Quiz) -> str:
    return request.build_absolute_uri(reverse("quiz", args=[quiz.slug]))


@admin_required
def run_detail(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)
    context = {
        "run": run,
        "quiz": run.quiz,
        "is_open": run.status == QuizRun.Status.OPEN,
        "public_url": _public_url(request, run.quiz),
        "submitted": run.attempts.filter(status=Attempt.Status.SUBMITTED).count(),
    }
    return page(request, "admin/run.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def run_close(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = get_object_or_404(QuizRun, pk=run_id)
    authoring.close_run(run, admin_id=str(request.user.pk))
    return redirect("admin_run", run.id)


@admin_required
def quiz_qr(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    buffer = io.BytesIO()
    segno.make(_public_url(request, quiz), error="m").save(buffer, kind="svg", scale=4, border=2)
    return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")
