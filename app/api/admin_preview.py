"""Preview of a draft or revision, on the participant's templates (ADR-0044)."""

from typing import Any
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from app.api import i18n, pass_mark
from app.api.admin_auth import admin_required
from app.api.admin_quizzes import problem_text
from app.api.play import (
    _answers,
    _error,
    _message_fragment,
    _respond,
    _revealed,
    received_time,
    uploads,
    with_files,
    without_files,
)
from app.api.rendering import (
    flow_options,
    identity_context,
    media_storage,
    page,
    question_html,
    question_settings,
    result_sources,
    reveal_context,
)
from app.contracts import ASK_WHEN, ImageRefused
from app.domain import attempts, authoring, participants, preview, reveal, selection, settings
from app.domain.models import Attempt, Quiz, QuizRevision

PREVIEW_PHOTO = "0" * 32


def _check_photo(data: bytes, _stored: list[str]) -> str:
    """Refused as in a run, but kept nowhere, so the answer carries a stand-in for an asset."""
    storage = media_storage()
    if storage is None:
        raise ImageRefused(str(_("Photos cannot be stored on this installation.")))
    storage.check_participant_image(data)
    return PREVIEW_PHOTO


def _bar(
    quiz: Quiz, problems: list[str] | None = None, switch: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "text": _("Preview. Nothing is stored."),
        "links": [
            {
                "href": reverse("admin_quiz_edit", args=[quiz.id]),
                "label": _("Back to the editor"),
            },
            *([switch] if switch else []),
        ],
        "problems": problems or [],
    }


def _locale(request: HttpRequest, quiz: Quiz, revision: QuizRevision | None) -> str:
    if revision is not None:
        snapshot = revision.snapshot_json
        return i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    return i18n.negotiate(request, quiz.supported_locales, quiz.default_locale)


def _questions(attempt: Attempt, locale: str) -> list[dict[str, Any]]:
    bad = preview.unusable(attempt, locale)
    quiz = attempt.run.quiz
    rows = []
    for question in attempts.questions_of(attempt):
        if question["id"] in bad:
            rows.append(
                {
                    "id": question["id"],
                    "notice": _("This question cannot be shown yet: %(reason)s")
                    % {"reason": bad[question["id"]]},
                }
            )
            continue
        html = question_html(
            question,
            locale,
            question_settings(quiz, question),
            None,
            False,
            attempts.option_seed_for(attempt, question),
        )
        rows.append({"id": question["id"], "html": html})
    return rows


def _urls(quiz: Quiz) -> dict[str, Any]:
    return {
        "submit_url": reverse("admin_preview_submit", args=[quiz.id]),
        "check_url": reverse("admin_preview_check", args=[quiz.id]),
        "preview": True,
    }


def _message_page(
    request: HttpRequest, quiz: Quiz, locale: str, problems: list[str], message: Any = None
) -> HttpResponse:
    context = {
        "branding_quiz": quiz,
        "mode_bar": _bar(quiz, problems),
        "preview_message": message,
        "restart_url": reverse("admin_preview", args=[quiz.id]),
    }
    return _respond(request, "public/_preview_message.html", context, locale)


def _limit_switch(request: HttpRequest, quiz: Quiz, timed: bool) -> dict[str, str] | None:
    """Mostly a preview is for looking at questions; this simulates whether it can be finished."""
    if settings.attempt_limit_seconds(quiz) is None:
        return None
    if timed:
        return {"href": request.path, "label": str(_("Turn the time limit off"))}
    return {"href": f"{request.path}?timed=1", "label": str(_("Try it with the time limit"))}


@admin_required
@require_GET
def preview_page(
    request: HttpRequest, quiz_id: UUID, revision_no: int | None = None
) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    revision = None
    if revision_no is not None:
        revision = quiz.revisions.filter(revision_no=revision_no).first()
        if revision is None:
            raise Http404
        if revision.status == QuizRevision.Status.DRAFT:
            revision = None
    locale = _locale(request, quiz, revision)
    timed = request.GET.get("timed") == "1"
    try:
        started = preview.start(quiz, revision, timed=timed)
    except selection.CannotDraw:
        problems = authoring.validate_for_publication(quiz)
        texts = [problem_text(problem) for problem in problems]
        return _message_page(request, quiz, locale, texts)
    texts = [problem_text(problem) for problem in started.problems]
    questions = _questions(started.attempt, locale)
    if not questions:
        return _message_page(request, quiz, locale, texts)
    context = {
        "branding_quiz": quiz,
        "mode_bar": _bar(quiz, texts, _limit_switch(request, quiz, timed)),
        "attempt": started.attempt,
        "time_left": attempts.time_left(started.attempt),
        "attempt_token": started.token,
        "submission_key": "",
        "questions": questions,
        "flow": flow_options(attempts.flow_of(started.attempt)),
        "uploads": uploads(started.attempt),
        # A preview has no start page, so the fields sit in the form whenever they are asked.
        # What they hold is never read.
        "identity": identity_context(participants.rules_for_quiz(quiz) | {ASK_WHEN: "end"}),
        **_urls(quiz),
    }
    return page(
        request, "public/play.html", context | {"partial": "public/_questions.html"}, locale
    )


def _stale(request: HttpRequest, quiz: Quiz) -> HttpResponse:
    locale = i18n.negotiate(request, quiz.supported_locales, quiz.default_locale)
    message = _("The draft changed in the meantime. Start the preview again.")
    return _message_page(request, quiz, locale, [], message)


@admin_required
@require_POST
def submit(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    received_at = received_time(request)
    automatic = request.POST.get("auto_submit") == "1"
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        attempt = preview.load(request.POST.get("attempt_token", ""), quiz)
    except preview.PreviewStale:
        return _stale(request, quiz)
    snapshot = attempt.revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    preview.keep_usable(attempt, locale)
    answers = _answers(request)
    without_files(attempt, answers)
    try:
        preview.check_time(attempt, received_at)
        with translation.override(locale):
            with_files(request, attempt, answers, _check_photo, lenient=automatic)
        result = preview.score(attempt, answers, lenient=automatic)
        revealed = _revealed(attempt, answers, locale)
    except ImageRefused as error:
        if request.headers.get("HX-Request") == "true":
            return _message_fragment({"message": str(error)}, locale, 400)
        response = _message_page(request, quiz, locale, [], str(error))
        response.status_code = 400
        return response
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    except LookupError:
        return _error(request, "revision_unavailable", locale)
    context = {
        "branding_quiz": quiz,
        "mode_bar": _bar(quiz),
        "revealed": revealed,
        "earned": result.earned_points,
        "maximum": result.max_points,
        "sources": result_sources(
            attempts.questions_of(attempt), settings.resolve(settings.SHOW_SOURCES, quiz), locale
        ),
        "percentage": result.percentage_display,
        "correct_count": result.correct_count,
        "pending": result.pending,
        "time_ran_out": automatic,
        "after_close_note": _preview_note(attempt, locale),
        "back_url": reverse("admin_preview", args=[quiz.id]),
        "back_label": _("Preview again"),
        **pass_mark.preview_context(
            quiz,
            locale,
            score=result.earned_points,
            maximum=result.max_points,
            pending=result.pending,
        ),
    }
    return _respond(request, "public/_result.html", context, locale)


def _preview_note(attempt: Attempt, locale: str) -> str:
    """A preview lists the answers at the end; the note says what a real run would do."""
    if not attempts.flow_of(attempt).get("after_close"):
        return ""
    return reveal.rehearsal_note(locale)


@admin_required
@require_POST
def check(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        attempt = preview.load(request.POST.get("attempt_token", ""), quiz)
    except preview.PreviewStale:
        return _stale(request, quiz)
    snapshot = attempt.revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    flow = attempts.flow_of(attempt)
    if flow["moment"] != settings.RevealMoment.AFTER_EACH:
        return _error(request, "reveal_not_allowed", locale)
    preview.keep_usable(attempt, locale)
    question_id = request.POST.get("check_question", "")
    question = next((q for q in attempts.questions_of(attempt) if q["id"] == question_id), None)
    if question is None:
        return _error(request, "not_in_attempt", locale)
    answers = _answers(request)
    without_files(attempt, answers)
    answer = answers.get(question_id)
    answer = None if reveal.is_blank(answer) else answer
    try:
        revealed = reveal.of_question(question, answer, flow["level"], locale)
        row = reveal_context(question, revealed, answer, locale, with_prompt=False, quiz=quiz)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    translation.activate(locale)
    return HttpResponse(render_to_string("public/_reveal.html", {"revealed": row}, request))
