"""The admin's side of test links (ADR-0044). The tester's side is in `public.test_link`."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.admin_quizzes import problem_text
from app.api.admin_workspace import workspace
from app.api.rendering import delete_images, page
from app.domain import authoring, run_links
from app.domain.models import Attempt, Quiz, QuizRevision, QuizRun, RunTestLink

DRAFT = "draft"
TIME_FORMAT = "%Y-%m-%d %H:%M"


def _versions(quiz: Quiz) -> list[tuple[str, str]]:
    versions = [(DRAFT, _("Draft (a frozen copy)"))] if authoring.has_draft(quiz) else []
    published = quiz.revisions.exclude(status=QuizRevision.Status.DRAFT)
    return versions + [
        (str(revision.revision_no), _("Revision %(no)s") % {"no": revision.revision_no})
        for revision in published.order_by("-revision_no")
    ]


def _plain(value: Decimal | None) -> str:
    return f"{(value or Decimal(0)).normalize():f}"


def _attempt_row(attempt: Attempt) -> dict[str, str]:
    submitted = attempt.status in Attempt.FINISHED
    waiting = attempt.status == Attempt.Status.PENDING_GRADING
    return {
        "status": _("Waiting for grading")
        if waiting
        else (_("Submitted") if submitted else _("In progress")),
        "score": f"{_plain(attempt.score)} / {_plain(attempt.max_score)}" if submitted else "",
        "duration": f"{attempt.duration_ms // 1000} s" if attempt.duration_ms is not None else "",
        "started": attempt.started_at.astimezone(UTC).strftime(TIME_FORMAT),
    }


def _state(link: RunTestLink) -> str:
    if link.run.status != QuizRun.Status.OPEN:
        return _("Cancelled")
    return _("Active") if link.is_playable(timezone.now()) else _("Ended")


def _row(request: HttpRequest, link: RunTestLink) -> dict[str, Any]:
    revision = link.run.current_revision
    is_copy = revision.status == QuizRevision.Status.TEST_COPY
    return {
        "id": link.id,
        "run_id": link.run_id,
        "version": (
            _("Copy of the draft from %(when)s")
            % {"when": revision.published_at.astimezone(UTC).strftime(TIME_FORMAT)}
            if is_copy
            else _("Revision %(no)s") % {"no": revision.revision_no}
        ),
        "address": request.build_absolute_uri(reverse("test_link", args=[link.token])),
        "state": _state(link),
        "is_active": link.run.status == QuizRun.Status.OPEN,
        "created": link.created_at.astimezone(UTC).strftime(TIME_FORMAT),
        "end": link.expires_at.astimezone(UTC).strftime(TIME_FORMAT) if link.expires_at else None,
        "attempts": [
            _attempt_row(attempt)
            for attempt in Attempt.objects.filter(run=link.run_id).order_by("-started_at")
        ],
    }


def _links_page(
    request: HttpRequest, quiz: Quiz, form: dict[str, Any] | None = None
) -> HttpResponse:
    links = RunTestLink.objects.filter(run__quiz=quiz).select_related(
        "run", "run__current_revision", "run__quiz"
    )
    context = workspace(quiz, "tests") | {
        "versions": _versions(quiz),
        "rows": [_row(request, link) for link in links.order_by("-created_at")],
        "chosen": "",
        "expires_at": "",
        **(form or {}),
    }
    return page(request, "admin/test_links.html", context, request.locale)  # type: ignore[attr-defined]


def _end(value: str) -> datetime | None:
    """Admin times are in UTC everywhere. Raises ValueError for what cannot be used."""
    if not value:
        return None
    end = datetime.fromisoformat(value).replace(tzinfo=UTC)
    if end <= timezone.now():
        raise ValueError("in the past")
    return end


def _create(request: HttpRequest, quiz: Quiz) -> HttpResponse:
    chosen = request.POST.get("version", "")
    expires_at = request.POST.get("expires_at", "").strip()
    form: dict[str, Any] = {"chosen": chosen, "expires_at": expires_at}
    if chosen not in dict(_versions(quiz)):
        return _links_page(request, quiz, form | {"error": _("Choose a version.")})
    try:
        end = _end(expires_at)
    except ValueError:
        return _links_page(
            request, quiz, form | {"error": _("The end must be a valid time in the future.")}
        )
    revision = None if chosen == DRAFT else quiz.revisions.get(revision_no=int(chosen))
    try:
        run_links.create(quiz, revision, expires_at=end, admin_id=str(request.user.pk))
    except authoring.PublicationError as error:
        problems = [problem_text(problem) for problem in error.problems]
        return _links_page(request, quiz, form | {"problems": problems})
    except authoring.QuizArchived:
        return redirect("admin_quiz_tests", quiz.id)
    return redirect("admin_quiz_tests", quiz.id)


@admin_required
def links_page(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method == "POST":
        return _create(request, quiz)
    return _links_page(request, quiz)


def _link(link_id: UUID) -> RunTestLink:
    return get_object_or_404(RunTestLink.objects.select_related("run", "run__quiz"), pk=link_id)


@admin_required
@require_POST
def link_cancel(request: HttpRequest, link_id: UUID) -> HttpResponse:
    link = _link(link_id)
    run_links.cancel(link, admin_id=str(request.user.pk))
    return redirect("admin_quiz_tests", link.run.quiz_id)


def _confirmed(request: HttpRequest, link: RunTestLink, message: str, action: str) -> HttpResponse:
    context = {
        "quiz": link.run.quiz,
        "message": message,
        "action": reverse(action, args=[link.id]),
        "cancel": reverse("admin_quiz_tests", args=[link.run.quiz_id]),
    }
    return page(request, "admin/confirm.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def link_delete(request: HttpRequest, link_id: UUID) -> HttpResponse:
    link = _link(link_id)
    if request.method != "POST":
        message = _("Delete this test link with all its attempts? This cannot be undone.")
        return _confirmed(request, link, message, "admin_test_link_delete")
    quiz_id = link.run.quiz_id
    delete_images(run_links.delete(link, admin_id=str(request.user.pk)))
    return redirect("admin_quiz_tests", quiz_id)


@admin_required
def link_attempts_delete(request: HttpRequest, link_id: UUID) -> HttpResponse:
    link = _link(link_id)
    if request.method != "POST":
        message = _("Delete all attempts of this test link? This cannot be undone.")
        return _confirmed(request, link, message, "admin_test_link_attempts_delete")
    delete_images(run_links.delete_attempts(link, admin_id=str(request.user.pk)))
    return redirect("admin_quiz_tests", link.run.quiz_id)
