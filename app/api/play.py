"""Start and submit. Forms work with HTMX and without it; the same service decides everything."""

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any
from uuid import UUID

from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from app.api import i18n
from app.api.rendering import (
    delete_images,
    flow_options,
    media_storage,
    mode_bar_of,
    page,
    question_html,
    question_settings,
    result_sources,
    reveal_context,
)
from app.contracts import MAX_PHOTO_BYTES, ImageRefused
from app.domain import attempts, grading, reveal, settings, tokens, visibility
from app.domain.models import Attempt, QuizRun
from app.kernel import registry

KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
SUBMIT_ROUTE = re.compile(r"/a/([0-9a-fA-F-]{36})/submit")
STOP_POLLING = 286
STATUS = {
    "invalid_request": 400,
    "invalid_answer": 400,
    "invalid_token": 403,
    "not_found": 404,
    "run_closed": 409,
    "already_submitted": 409,
    "submission_key_used": 409,
    "attempt_switched": 409,
    "attempt_expired": 410,
    "revision_unavailable": 503,
    "reveal_not_allowed": 403,
    "not_in_attempt": 403,
    "test_link_ended": 410,
}
MESSAGES = {
    "invalid_request": _("The form could not be read. Please try again."),
    "invalid_answer": _("An answer could not be read. Please check your answers."),
    "invalid_token": _("This attempt is not valid. Please start again."),
    "not_found": _("This attempt does not exist."),
    "run_closed": _("This run has ended."),
    "already_submitted": _("This attempt has already been submitted."),
    "submission_key_used": _("This attempt has already been submitted."),
    "attempt_switched": _(
        "This attempt was replaced by a newer version of the quiz. Please reload the page."
    ),
    "attempt_expired": _("The time for this attempt has run out."),
    "revision_unavailable": _("This quiz is temporarily unavailable."),
    "reveal_not_allowed": _("This quiz does not show answers now."),
    "not_in_attempt": _("This question is not part of your attempt."),
    "test_link_ended": _("This test has ended."),
}


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _respond(
    request: HttpRequest, partial: str, context: dict[str, Any], locale: str
) -> HttpResponse:
    if _is_htmx(request):
        translation.activate(locale)
        return HttpResponse(render_to_string(partial, context | {"locale": locale}, request))
    return page(request, "public/play.html", context | {"partial": partial}, locale)


def _error(request: HttpRequest, code: str, locale: str) -> HttpResponse:
    context = {"message": MESSAGES[code]}
    if _is_htmx(request):
        return _message_fragment(context, locale, STATUS[code])
    context |= {"partial": "public/_error_page.html"}
    return page(request, "public/play.html", context, locale, status=STATUS[code])


def _message_fragment(context: dict[str, Any], locale: str, status: int) -> HttpResponse:
    translation.activate(locale)
    response = HttpResponse(render_to_string("public/_error.html", context), status=status)
    response["HX-Retarget"] = "#play-message"
    return response


def accepts_upload(request: HttpRequest) -> bool:
    """Whether this request may carry a photo. The body stays unread (ADR-0047).

    An attempt already finished is let through too, as a repeat after a lost answer deserves its
    result. Nothing of it is stored.
    """
    match = SUBMIT_ROUTE.fullmatch(request.path)
    if match is None:
        return False
    try:
        found = Attempt.objects.filter(pk=UUID(match[1]))
        attempt = found.select_related("run", "revision").first()
    except ValueError:
        return False
    if attempt is None or attempt.status == Attempt.Status.SWITCHED:
        return False
    if attempt.status == Attempt.Status.IN_PROGRESS and attempt.run.status != QuizRun.Status.OPEN:
        return False
    return uploads(attempt)


def uploads(attempt: Attempt) -> bool:
    try:
        return any(attempts.file_fields(question) for question in attempts.questions_of(attempt))
    except registry.UnknownPort:
        return False


def _locale(request: HttpRequest, locales: Sequence[str], default: str) -> str | None:
    """None when the form body itself cannot be read."""
    try:
        return i18n.negotiate(request, locales, default)
    except RequestDataTooBig, TooManyFieldsSent:
        return None


def _questions(
    attempt: Attempt,
    locale: str,
    answers: Mapping[str, Any] | None = None,
    changed: Collection[str] = (),
) -> list[dict[str, Any]]:
    """What this attempt was given, drawn the same way every time."""
    quiz = attempt.run.quiz
    return [
        {
            "id": question["id"],
            "html": question_html(
                question,
                locale,
                question_settings(quiz, question),
                (answers or {}).get(question["id"]),
                question["id"] in changed,
                attempts.option_seed_for(attempt, question),
            ),
        }
        for question in attempts.questions_of(attempt)
    ]


@csrf_exempt
@require_POST
def start(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = QuizRun.all_kinds.filter(pk=run_id).select_related("current_revision").first()
    if run is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = run.current_revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    try:
        started = attempts.start(run)
        questions = _questions(started.attempt, locale)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    context = {
        "palette_quiz": run.quiz,
        "mode_bar": mode_bar_of(run),
        "attempt": started.attempt,
        "attempt_token": started.token,
        "submission_key": started.submission_key,
        "questions": questions,
        "flow": flow_options(attempts.flow_of(started.attempt)),
        "uploads": uploads(started.attempt),
    }
    return _respond(request, "public/_questions.html", context, locale)


def _answers(request: HttpRequest) -> dict[str, dict[str, str | list[str]]]:
    """Inputs are named `<question id>:<field>`; anything else in the form is ignored.

    A field whose name ends in `[]` holds a list of every value sent under that name.
    """
    answers: dict[str, dict[str, str | list[str]]] = {}
    for name, values in request.POST.lists():
        question_id, _sep, field = name.partition(":")
        if not (question_id and field):
            continue
        if field.endswith("[]"):
            answers.setdefault(question_id, {})[field[:-2]] = values
        else:
            answers.setdefault(question_id, {})[field] = values[-1]
    return answers


def without_files(attempt: Attempt, answers: dict[str, Any]) -> None:
    """A file field's value comes only from a file received, so a form cannot name an asset."""
    for question in attempts.questions_of(attempt):
        if question["id"] in answers:
            for field in attempts.file_fields(question):
                answers[question["id"]].pop(field, None)


def with_files(
    request: HttpRequest,
    attempt: Attempt,
    answers: dict[str, Any],
    read: Callable[[bytes, list[str]], str],
) -> list[str]:
    """Hands each file to `read` for an asset id. Returns the ids; a refusal leaves none."""
    stored: list[str] = []
    try:
        for question in attempts.questions_of(attempt):
            for field in attempts.file_fields(question):
                upload = request.FILES.get(f"{question['id']}:{field}")
                if upload is not None:
                    if upload.size > MAX_PHOTO_BYTES:
                        raise ImageRefused(str(_("A photo can be at most 15 MB.")))
                    asset = read(upload.read(), stored)
                    stored.append(asset)
                    answers.setdefault(question["id"], {})[field] = asset
    except ImageRefused:
        delete_images(stored)
        raise
    return stored


def _store_photo(attempt: Attempt) -> Callable[[bytes, list[str]], str]:
    storage = media_storage()
    if storage is None:
        message = _("Photos cannot be stored on this installation.")

        def refuse(_data: bytes, _stored: list[str]) -> str:
            raise ImageRefused(str(message))

        return refuse
    known = grading.run_assets(attempt.run)
    return lambda data, stored: storage.store_participant_image(data, run_assets=known + stored)


def _from_stored_rows(attempt: Attempt, answers: dict[str, Any]) -> None:
    """What this attempt holds is the truth, for a repeat too, which stores nothing new."""
    for row in attempt.answers.all():
        answers[row.question_id] = row.answer_json


def _refused(
    request: HttpRequest, attempt: Attempt, locale: str, error: ImageRefused
) -> HttpResponse:
    if _is_htmx(request):
        return _message_fragment({"message": str(error)}, locale, STATUS["invalid_answer"])
    return _try_again(request, attempt, locale, str(error))


def _try_again(
    request: HttpRequest, attempt: Attempt, locale: str, message: Any = None
) -> HttpResponse:
    """Without a script the page is replaced, so the form comes back with the answers in it."""
    answers = _answers(request)
    without_files(attempt, answers)
    context = {
        "palette_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "attempt": attempt,
        "attempt_token": request.POST.get("attempt_token", ""),
        "submission_key": request.POST.get("submission_key", ""),
        "questions": _questions(attempt, locale, answers),
        "flow": flow_options(attempts.flow_of(attempt)),
        "uploads": uploads(attempt),
        "partial": "public/_questions.html",
        "play_message": message or MESSAGES["invalid_answer"],
    }
    return page(request, "public/play.html", context, locale, status=STATUS["invalid_answer"])


def _revealed(attempt: Attempt, answers: Mapping[str, Any], locale: str) -> list[dict[str, Any]]:
    """After each question also lists them here, because a page without a script saw nothing yet.

    A repeated submission may carry anything, and its score is already stored.
    """
    flow = attempts.flow_of(attempt)
    if flow["moment"] == settings.RevealMoment.NEVER:
        return []
    rows = []
    for question in attempts.questions_of(attempt):
        answer = answers.get(question["id"])
        try:
            revealed = reveal.of_question(question, answer, flow["level"], locale)
        except attempts.AttemptError:
            answer = None
            revealed = reveal.of_question(question, None, flow["level"], locale)
        rows.append(
            reveal_context(
                question, revealed, answer, locale, with_prompt=True, quiz=attempt.run.quiz
            )
        )
    return rows


def _result_link(attempt: Attempt, result: attempts.AttemptResult) -> str | None:
    if not result.pending and not visibility.has_more_to_see(attempt):
        return None
    return reverse("result", args=[tokens.issue_result(attempt.id)])


@csrf_exempt
@require_POST
def submit(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("revision").first()
    if attempt is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = attempt.revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    key = request.POST.get("submission_key", "")
    if not KEY.fullmatch(key):
        return _error(request, "invalid_request", locale)
    token = request.POST.get("attempt_token", "")
    answers = _answers(request)
    stored: list[str] = []
    try:
        without_files(attempt, answers)
        if request.FILES and attempt.status == Attempt.Status.IN_PROGRESS:
            attempts.verify_open(attempt_id, token)
            with translation.override(locale):
                stored = with_files(request, attempt, answers, _store_photo(attempt))
        result = attempts.submit(attempt_id, token, answers, key)
    except ImageRefused as error:
        return _refused(request, attempt, locale, error)
    except attempts.AttemptError as error:
        delete_images(stored)
        if error.code != "invalid_answer" or _is_htmx(request):
            return _error(request, error.code, locale)
        try:
            return _try_again(request, attempt, locale)
        except registry.UnknownPort:
            return _error(request, "revision_unavailable", locale)
    except registry.UnknownPort:
        delete_images(stored)
        return _error(request, "revision_unavailable", locale)
    except Exception:
        delete_images(stored)
        raise
    _from_stored_rows(attempt, answers)
    kept = {row.asset_id for row in attempt.answers.all()}
    delete_images([asset for asset in stored if asset not in kept])
    try:
        revealed = _revealed(attempt, answers, locale)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    context = {
        "palette_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "revealed": revealed,
        "earned": result.earned_points,
        "maximum": result.max_points,
        "sources": result_sources(attempts.questions_of(attempt), attempt.run.quiz, locale),
        "percentage": result.percentage_display,
        "correct_count": result.correct_count,
        "pending": result.pending,
        "result_link": _result_link(attempt, result),
        "remember_quiz": attempt.run.quiz.slug if attempt.run.kind == QuizRun.Kind.NORMAL else "",
    }
    return _respond(request, "public/_result.html", context, locale)


@csrf_exempt
@require_POST
def check(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    """One question's reveal as a fragment. Only the script asks for it, and nothing is stored."""
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("revision").first()
    if attempt is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = attempt.revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    question_id = request.POST.get("check_question", "")
    try:
        question, level = attempts.check(
            attempt_id, request.POST.get("attempt_token", ""), question_id
        )
        answers = _answers(request)
        without_files(attempt, answers)
        answer = answers.get(question_id)
        answer = None if reveal.is_blank(answer) else answer
        revealed = reveal.of_question(question, answer, level, locale)
        row = reveal_context(
            question, revealed, answer, locale, with_prompt=False, quiz=attempt.run.quiz
        )
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    translation.activate(locale)
    return HttpResponse(render_to_string("public/_reveal.html", {"revealed": row}, request))


@require_GET
def revision_status(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    """Polled while playing. Status 286 tells HTMX to stop, 204 to leave the page as it is."""
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("run", "revision").first()
    if (
        attempt is None
        or attempt.status in Attempt.FINISHED
        or attempt.run.status != QuizRun.Status.OPEN
    ):
        return HttpResponse(status=STOP_POLLING)
    if not attempts.must_switch(attempt):
        return HttpResponse(status=204)
    snapshot = attempt.revision.snapshot_json
    locale = i18n.negotiate(request, snapshot["locales"], snapshot["default_locale"])
    translation.activate(locale)
    context = {"attempt": attempt}
    return HttpResponse(render_to_string("public/_switch_notice.html", context, request))


@csrf_exempt
@require_POST
def switch(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("revision").first()
    if attempt is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = attempt.revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    token = request.POST.get("attempt_token", "")
    try:
        answers = _answers(request)
        without_files(attempt, answers)
        result = attempts.switch(attempt_id, token, answers)
        current = result.started.attempt.revision.snapshot_json
        locale = i18n.negotiate(request, current["locales"], current["default_locale"])
        questions = _questions(result.started.attempt, locale, result.answers, result.changed)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    context = {
        "palette_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "attempt": result.started.attempt,
        "attempt_token": result.started.token,
        "submission_key": result.started.submission_key,
        "questions": questions,
        "flow": flow_options(attempts.flow_of(result.started.attempt)),
        "uploads": uploads(result.started.attempt),
    }
    return _respond(request, "public/_questions.html", context, locale)
