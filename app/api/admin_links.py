"""The admin's side of test links (ADR-0044). The tester's side is in `public.test_link`."""

from datetime import datetime
from typing import Any
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from app.api.admin_auth import admin_required
from app.api.admin_common import confirm_page, plain
from app.api.admin_quizzes import problem_text
from app.api.admin_workspace import workspace
from app.api.inline_name import NameField, render_field, wants_partial
from app.api.rendering import delete_images, page
from app.domain import authoring, clock, run_links
from app.domain.models import Attempt, Quiz, QuizRevision, QuizRun, RunTestLink

DRAFT = "draft"


def _versions(quiz: Quiz) -> list[tuple[str, str]]:
    versions = [(DRAFT, _("Draft (a frozen copy)"))] if authoring.has_draft(quiz) else []
    published = quiz.revisions.exclude(status=QuizRevision.Status.DRAFT)
    return versions + [
        (str(revision.revision_no), _("Revision %(no)s") % {"no": revision.revision_no})
        for revision in published.order_by("-revision_no")
    ]


def _attempt_row(attempt: Attempt) -> dict[str, str]:
    submitted = attempt.status in Attempt.FINISHED
    waiting = attempt.status == Attempt.Status.PENDING_GRADING
    return {
        "status": _("Waiting for grading")
        if waiting
        else (_("Submitted") if submitted else _("In progress")),
        "score": f"{plain(attempt.score, none='0')} / {plain(attempt.max_score, none='0')}"
        if submitted
        else "",
        "duration": f"{attempt.duration_ms // 1000} s" if attempt.duration_ms is not None else "",
        "started": clock.shown(attempt.started_at),
    }


def _state(link: RunTestLink) -> str:
    if link.run.status != QuizRun.Status.OPEN:
        return _("Cancelled")
    return _("Active") if link.is_playable(timezone.now()) else _("Ended")


def _admins_origin(request: HttpRequest) -> str:
    return request.build_absolute_uri("/").removesuffix("/")


def _address(request: HttpRequest, link: RunTestLink) -> str:
    """The saved origin of this link, or the admin's own; the path with the token is fixed."""
    return (link.shown_origin or _admins_origin(request)) + reverse("test_link", args=[link.token])


def _address_field(
    request: HttpRequest,
    link: RunTestLink,
    *,
    editing: bool = False,
    value: str | None = None,
    error: str = "",
    saved: bool = False,
) -> NameField:
    """The pencil at the address (AC-167): only the scheme, host and port can be changed."""
    path = reverse("test_link", args=[link.token])
    page_url = reverse("admin_quiz_tests", args=[link.run.quiz_id])
    address_url = reverse("admin_test_link_address", args=[link.id])
    origin = link.shown_origin or _admins_origin(request)
    if editing and value is not None:  # a refused value is shown as typed
        origin = value
    return NameField(
        label=_("Address of the link"),
        field="address",
        key=str(link.id),
        value=origin,
        save_url=address_url,
        edit_url=f"{address_url}?edit=1",
        view_url=address_url,
        edit_page=f"{page_url}?edit=address-{link.id}",
        back_page=page_url,
        max_length=run_links.MAX_ORIGIN,
        editing=editing,
        error=error,
        note="" if editing else _("Only changes what is shown for copying."),
        saved=saved,
        placeholder=_admins_origin(request),
        link=_address(request, link),
        suffix=path,
        pencil_label=_("Edit the address"),
        required=False,
    )


def _row(request: HttpRequest, link: RunTestLink, editing: str = "") -> dict[str, Any]:
    revision = link.run.current_revision
    is_copy = revision.status == QuizRevision.Status.TEST_COPY
    archived = link.run.quiz.archived_at is not None
    return {
        "id": link.id,
        "run_id": link.run_id,
        "version": (
            _("Copy of the draft from %(when)s") % {"when": clock.shown(revision.published_at)}
            if is_copy
            else _("Revision %(no)s") % {"no": revision.revision_no}
        ),
        "address": _address(request, link),
        "address_field": None
        if archived
        else _address_field(request, link, editing=editing == f"address-{link.id}"),
        "state": _state(link),
        "is_active": link.run.status == QuizRun.Status.OPEN,
        "created": clock.shown(link.created_at),
        "end": clock.shown(link.expires_at) if link.expires_at else None,
        "attempts": [
            _attempt_row(attempt)
            for attempt in Attempt.objects.filter(run=link.run_id).order_by("-started_at")
        ],
    }


def _links_page(
    request: HttpRequest,
    quiz: Quiz,
    form: dict[str, Any] | None = None,
    *,
    status: int = 200,
    field: NameField | None = None,
) -> HttpResponse:
    links = RunTestLink.objects.filter(run__quiz=quiz).select_related(
        "run", "run__current_revision", "run__quiz"
    )
    editing = request.GET.get("edit", "") if request.method == "GET" else ""
    context = workspace(quiz, "tests") | {
        "versions": _versions(quiz),
        "rows": [_row(request, link, editing) for link in links.order_by("-created_at")],
        "chosen": "",
        "expires_at": "",
        **(form or {}),
    }
    if field is not None and quiz.archived_at is None:
        for row in context["rows"]:
            if row["id"] == UUID(field.key):
                row["address_field"] = field
    locale = request.locale  # type: ignore[attr-defined]
    return page(request, "admin/test_links.html", context, locale, status=status)


def _end(value: str) -> datetime | None:
    """Raises ValueError for what cannot be used."""
    if not value:
        return None
    end = clock.parse_local(value)
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
    return confirm_page(
        request,
        quiz=link.run.quiz,
        message=message,
        action=reverse(action, args=[link.id]),
        cancel=reverse("admin_quiz_tests", args=[link.run.quiz_id]),
    )


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


@admin_required
@require_http_methods(["GET", "POST"])
def link_address(request: HttpRequest, link_id: UUID) -> HttpResponse:
    """The shown address of one link on the spot: the display, the field and the save."""
    link = _link(link_id)
    quiz = link.run.quiz
    if request.method == "GET":
        archived = quiz.archived_at is not None
        editing = request.GET.get("edit") == "1" and not archived
        if not wants_partial(request):
            suffix = f"?edit=address-{link.id}" if editing else ""
            return redirect(reverse("admin_quiz_tests", args=[quiz.id]) + suffix)
        if archived:  # the page shows a plain link then, without a pencil
            address = _address(request, link)
            return HttpResponse(format_html('<a href="{0}" rel="noreferrer">{0}</a>', address))
        return render_field(request, _address_field(request, link, editing=editing))
    typed = request.POST.get("address", "")
    try:  # the prefilled address saved unchanged keeps following the admin's own address
        if run_links.clean_origin(typed) == _admins_origin(request):
            typed = ""
    except run_links.OriginInvalid:
        pass  # set_origin refuses it with its message
    try:
        run_links.set_origin(link, typed, admin_id=str(request.user.pk))
    except authoring.QuizArchived:
        error, status = _("This quiz is archived. Restore it to change it."), 409
    except run_links.OriginInvalid as refused:
        error, status = str(refused), 400
    else:
        if wants_partial(request):
            return render_field(request, _address_field(request, link, saved=True))
        return redirect("admin_quiz_tests", quiz.id)
    field = _address_field(request, link, editing=True, value=typed, error=error)
    if wants_partial(request):
        return render_field(request, field, status=status)
    return _links_page(request, quiz, status=status, field=field)
