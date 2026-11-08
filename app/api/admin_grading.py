"""The grading tab: what a person decides about stored answers (ADR-0047, AC-56).

Attempts appear as anonymous numbers, in the order they were submitted, until C2 brings names.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Value, When
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST
from markupsafe import Markup

from app.api.admin_auth import admin_required
from app.api.admin_workspace import workspace
from app.api.rendering import (
    delete_images,
    media_storage,
    page,
    question_label,
    with_media_urls,
)
from app.contracts import QuestionTypePlugin
from app.domain import attempts, grading, settings, visibility
from app.domain.models import Attempt, AttemptAnswer, Quiz, QuizRun
from app.kernel import registry

GALLERY_PAGE = 30
ATTEMPTS_PAGE = 20


def _runs(quiz: Quiz) -> list[QuizRun]:
    """The running one first, then from the newest. Test runs are reached from their link."""
    return sorted(
        quiz.runs.exclude(status=QuizRun.Status.SCHEDULED),
        key=lambda run: (run.status != QuizRun.Status.OPEN, -(run.run_no or 0)),
    )


def _chosen_run(request: HttpRequest, quiz: Quiz, runs: list[QuizRun]) -> QuizRun | None:
    wanted = request.GET.get("run") or request.POST.get("run")
    if not wanted:
        return runs[0] if runs else None
    try:
        return get_object_or_404(QuizRun.all_kinds, quiz=quiz, pk=UUID(wanted))
    except ValueError as exc:
        raise Http404 from exc


def _questions(run: QuizRun) -> dict[str, Mapping[str, Any]]:
    """Every question of the run's revisions, draw pools too. A newer revision wins a clash."""
    found: dict[str, Mapping[str, Any]] = {}
    for row in run.revision_rows.select_related("revision").order_by("active_from"):
        snapshot = row.revision.snapshot_json
        for question in snapshot.get("questions", []):
            found[question["id"]] = question
        for draw in snapshot.get("draws", []):
            for question in draw.get("pool", []):
                found[question["id"]] = question
    return found


def _numbers(run: QuizRun) -> dict[UUID, int]:
    finished = run.attempts.filter(status__in=Attempt.FINISHED).order_by("submitted_at", "id")
    return {
        attempt_id: number
        for number, attempt_id in enumerate(finished.values_list("id", flat=True), start=1)
    }


def _plain(value: Decimal | None) -> str:
    return "" if value is None else f"{value.normalize():f}"


def _photo_row(
    row: AttemptAnswer,
    number: int | None,
    quiz: Quiz,
    question: Mapping[str, Any] | None,
    **shown: Any,
) -> dict[str, Any]:
    return {
        "row": row,
        "number": number,
        "auto": _plain(row.auto_points),
        "maximum": _plain(row.manual_max),
        "value": _plain(row.manual_points),
        "waiting": row.manual_points is None and not row.removed,
        "approvable": visibility.may_be_approved(row, quiz, question),
        **shown,
    }


def _gallery(request: HttpRequest, quiz: Quiz, run: QuizRun) -> dict[str, Any]:
    questions = _questions(run)
    photos = AttemptAnswer.objects.filter(attempt__run=run, manual_max__gt=0)
    asked = sorted(set(photos.values_list("question_id", flat=True)))
    waiting = grading.waiting_rows(run).values_list("question_id", flat=True)
    current = request.GET.get("question") or request.POST.get("question")
    if not current:
        current = next(iter(waiting), None) or next(iter(asked), None)
    in_question = (
        photos.filter(question_id=current)
        .annotate(
            done=Case(
                When(manual_points__isnull=True, removed=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("done", "attempt__submitted_at", "id")
    )
    paged = Paginator(in_question, GALLERY_PAGE).get_page(request.GET.get("page"))
    numbers = _numbers(run)
    locale = request.locale  # type: ignore[attr-defined]
    question = questions.get(str(current))
    return {
        "view": settings.GradingView.BY_QUESTION.value,
        "question_id": current,
        "question_links": [
            {
                "id": question_id,
                "label": _label(questions.get(question_id), locale),
                "current": question_id == current,
                "waiting": sum(item == question_id for item in waiting),
            }
            for question_id in asked
        ],
        "question_label": _label(question, locale),
        "page_obj": paged,
        "page_number": paged.number,
        "photos": [_photo_row(row, numbers.get(row.attempt_id), quiz, question) for row in paged],
    }


def _label(question: Mapping[str, Any] | None, locale: str) -> str:
    return question_label(question, locale) if question else _("A question no longer in the quiz")


def _answer_html(question: Mapping[str, Any] | None, row: AttemptAnswer, locale: str) -> Any:
    """What the type says of a stored answer. It escapes through its own template."""
    if question is None:
        return ""
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
    except LookupError:
        return ""
    with translation.override(locale):
        definition = with_media_urls(question["definition"])
        return Markup(plugin.render_solution(definition, locale, row.answer_json))  # noqa: S704


def _by_attempt(request: HttpRequest, quiz: Quiz, run: QuizRun) -> dict[str, Any]:
    questions = _questions(run)
    locale = request.locale  # type: ignore[attr-defined]
    numbers = _numbers(run)
    finished = (
        run.attempts.filter(status__in=Attempt.FINISHED)
        .annotate(
            done=Case(
                When(status=Attempt.Status.PENDING_GRADING, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("done", "submitted_at", "id")
    )
    paged = Paginator(finished, ATTEMPTS_PAGE).get_page(request.GET.get("page"))
    cards = []
    for attempt in paged:
        rows = []
        for row in attempt.answers.order_by("id"):
            question = questions.get(row.question_id)
            shown = {
                "label": _label(question, locale),
                "answer_html": "" if row.manual_max > 0 else _answer_html(question, row, locale),
            }
            rows.append(_photo_row(row, numbers.get(attempt.id), quiz, question, **shown))
        cards.append(
            {
                "number": numbers.get(attempt.id),
                "score": _plain(attempt.score),
                "maximum": _plain(attempt.max_score),
                "pending": attempt.status == Attempt.Status.PENDING_GRADING,
                "rows": rows,
            }
        )
    return {
        "view": settings.GradingView.BY_ATTEMPT.value,
        "page_obj": paged,
        "page_number": paged.number,
        "cards": cards,
    }


def _grading_page(
    request: HttpRequest,
    quiz: Quiz,
    errors: Mapping[str, Mapping[str, str]] | None = None,
    status: int = 200,
) -> HttpResponse:
    runs = _runs(quiz)
    run = _chosen_run(request, quiz, runs)
    context = workspace(quiz, "grading") | {"runs": runs, "run": run, "errors": errors or {}}
    if run is not None and run not in runs:
        context["test_run"] = True
    if run is not None:
        view = settings.resolve(settings.GRADING_VIEW, quiz)
        if view == settings.GradingView.BY_ATTEMPT:
            context |= _by_attempt(request, quiz, run)
        else:
            context |= _gallery(request, quiz, run)
    return page(request, "admin/grading.html", context, request.locale, status=status)  # type: ignore[attr-defined]


@admin_required
@require_GET
def grading_page(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    return _grading_page(request, get_object_or_404(Quiz, pk=quiz_id))


def _answer(answer_id: UUID) -> AttemptAnswer:
    return get_object_or_404(
        AttemptAnswer.objects.select_related("attempt__run__quiz"), pk=answer_id
    )


def _back(request: HttpRequest, row: AttemptAnswer) -> str:
    """To the same run, question and page."""
    query = {"run": str(row.attempt.run_id)}
    for name in ("question", "page"):
        value = request.POST.get(name) or request.GET.get(name)
        if value:
            query[name] = value
    base = reverse("admin_quiz_grading", args=[row.attempt.run.quiz_id])
    return f"{base}?{urlencode(query)}"


def _question_of(row: AttemptAnswer) -> Mapping[str, Any] | None:
    return next(
        (
            question
            for question in attempts.questions_of(row.attempt)
            if question["id"] == row.question_id
        ),
        None,
    )


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _fragment(
    request: HttpRequest,
    row: AttemptAnswer,
    *,
    error: str | None = None,
    value: str | None = None,
) -> HttpResponse:
    run = row.attempt.run
    quiz = run.quiz
    shown = _photo_row(row, _numbers(run).get(row.attempt_id), quiz, _question_of(row))
    if value is not None:
        shown["value"] = value
    context = {
        "photo": shown,
        "error": error,
        "run": run,
        "question_id": request.POST.get("question", ""),
        "page_number": request.POST.get("page", ""),
    }
    translation.activate(request.locale)  # type: ignore[attr-defined]
    return HttpResponse(render_to_string("admin/_grading_photo.html", context, request))


@admin_required
@require_POST
def answer_points(request: HttpRequest, answer_id: UUID) -> HttpResponse:
    row = _answer(answer_id)
    typed = request.POST.get("points", "")
    try:
        grading.save_manual(row, Decimal(typed.strip().replace(",", ".")), admin_id=_admin(request))
    except InvalidOperation, grading.InvalidPoints:
        message = _("Points must be a number from 0 to %(maximum)s.") % {
            "maximum": _plain(row.manual_max)
        }
        if _is_htmx(request):
            return _fragment(request, row, error=message, value=typed)
        errors = {str(row.id): {"message": message, "value": typed}}
        return _grading_page(request, row.attempt.run.quiz, errors, status=400)
    if _is_htmx(request):
        return _fragment(request, row)
    return redirect(_back(request, row))


def _admin(request: HttpRequest) -> str:
    return str(request.user.pk)


@admin_required
def answer_delete(request: HttpRequest, answer_id: UUID) -> HttpResponse:
    row = _answer(answer_id)
    if request.method == "POST":
        asset = grading.remove_photo(row, admin_id=_admin(request))
        delete_images([asset] if asset else [])
        return redirect(_back(request, row))
    query = request.META.get("QUERY_STRING", "")
    action = reverse("admin_answer_delete", args=[row.id])
    context = {
        "quiz": row.attempt.run.quiz,
        "message": _(
            "Delete this photo? It is gone for good, and its points given by an admin become 0."
        ),
        "action": f"{action}?{query}" if query else action,
        "cancel": _back(request, row),
    }
    return page(request, "admin/confirm.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def answer_approve(request: HttpRequest, answer_id: UUID) -> HttpResponse:
    """For the public walkthrough, so only where this question's photos can be public at all."""
    row = _answer(answer_id)
    if not visibility.may_be_approved(row, row.attempt.run.quiz, _question_of(row)):
        return HttpResponseBadRequest()
    grading.set_approved(row, bool(request.POST.get("approved")), admin_id=_admin(request))
    if _is_htmx(request):
        return _fragment(request, row)
    return redirect(_back(request, row))


@admin_required
@require_GET
def answer_photo(request: HttpRequest, answer_id: UUID) -> FileResponse:
    row = _answer(answer_id)
    storage = media_storage()
    stored = storage.load(str(row.asset_id)) if storage and row.asset_id else None
    if stored is None:
        raise Http404
    response = FileResponse(Path(stored.path).open("rb"), content_type=stored.mime_type)
    response["Cache-Control"] = "private, no-store"
    return response
