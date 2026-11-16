"""Views of an attempt that follows a new quiz revision: reveal check, status poll and switch."""

from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.utils import translation
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from app.api import i18n
from app.api.play import (
    _answers,
    _identity_of_form,
    _locale,
    _questions,
    _respond,
    time_context,
    uploads,
    without_files,
)
from app.api.play_errors import (
    COUNTED_MESSAGES as COUNTED_MESSAGES,
)
from app.api.play_errors import (
    MESSAGES as MESSAGES,
)
from app.api.play_errors import (
    STATUS as STATUS,
)
from app.api.play_errors import (
    _error as _error,
)
from app.api.play_errors import (
    _is_htmx as _is_htmx,
)
from app.api.play_errors import (
    _limited as _limited,
)
from app.api.play_errors import (
    _message_fragment as _message_fragment,
)
from app.api.play_errors import (
    message_context as message_context,
)
from app.api.rendering import (
    flow_options,
    mode_bar_of,
    reveal_context,
)
from app.domain import (
    attempts,
    reveal,
)
from app.domain.models import Attempt, QuizRun
from app.kernel import registry

STOP_POLLING = 286


@csrf_exempt
@require_POST
def check(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    """One question's reveal as a fragment. Only the script asks for it, and nothing is stored."""
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("revision").first()
    if attempt is None:
        code = attempts.missing_code(attempt_id, request.POST.get("attempt_token", ""))
        return _error(request, code, request.locale)  # type: ignore[attr-defined]
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
        code = attempts.missing_code(attempt_id, request.POST.get("attempt_token", ""))
        return _error(request, code, request.locale)  # type: ignore[attr-defined]
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
        "branding_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "attempt": result.started.attempt,
        "attempt_token": result.started.token,
        "submission_key": result.started.submission_key,
        "questions": questions,
        "flow": flow_options(attempts.flow_of(result.started.attempt)),
        "uploads": uploads(result.started.attempt),
        "identity": _identity_of_form(request, attempt),
        **time_context(result.started.attempt),
    }
    return _respond(request, "public/_questions.html", context, locale)
