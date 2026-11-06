"""Start and submit. Forms work with HTMX and without it; the same service decides everything."""

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from app.api import i18n
from app.api.rendering import page, question_html
from app.domain import attempts
from app.domain.models import Attempt, QuizRun
from app.kernel import registry

KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
STATUS = {
    "invalid_request": 400,
    "invalid_answer": 400,
    "invalid_token": 403,
    "not_found": 404,
    "run_closed": 409,
    "already_submitted": 409,
    "submission_key_used": 409,
    "attempt_expired": 410,
    "revision_unavailable": 503,
}
MESSAGES = {
    "invalid_request": _("The form could not be read. Please try again."),
    "invalid_answer": _("An answer could not be read. Please check your answers."),
    "invalid_token": _("This attempt is not valid. Please start again."),
    "not_found": _("This attempt does not exist."),
    "run_closed": _("This round is closed."),
    "already_submitted": _("This attempt has already been submitted."),
    "submission_key_used": _("This attempt has already been submitted."),
    "attempt_expired": _("The time for this attempt has run out."),
    "revision_unavailable": _("This quiz is temporarily unavailable."),
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
        translation.activate(locale)
        response = HttpResponse(
            render_to_string("public/_error.html", context), status=STATUS[code]
        )
        response["HX-Retarget"] = "#play-message"
        return response
    context |= {"partial": "public/_error.html"}
    return page(request, "public/play.html", context, locale, status=STATUS[code])


def _locale(request: HttpRequest, locales: Sequence[str], default: str) -> str | None:
    """None when the form body itself cannot be read."""
    try:
        return i18n.negotiate(request, locales, default)
    except RequestDataTooBig, TooManyFieldsSent:
        return None


@csrf_exempt
@require_POST
def start(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = QuizRun.objects.filter(pk=run_id).select_related("current_revision").first()
    if run is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = run.current_revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    try:
        questions = [question_html(q, locale) for q in snapshot["questions"]]
        started = attempts.start(run)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    context = {
        "attempt": started.attempt,
        "attempt_token": started.token,
        "submission_key": started.submission_key,
        "questions": questions,
    }
    return _respond(request, "public/_questions.html", context, locale)


def _answers(request: HttpRequest) -> dict[str, dict[str, str]]:
    """Inputs are named `<question id>:<field>`; anything else in the form is ignored."""
    answers: dict[str, dict[str, str]] = {}
    for name, value in request.POST.items():
        question_id, _sep, field = name.partition(":")
        if question_id and field:
            answers.setdefault(question_id, {})[field] = value
    return answers


def _points(value: Decimal) -> str:
    return f"{value.normalize():f}"


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
    try:
        result = attempts.submit(attempt_id, token, _answers(request), key)
    except attempts.AttemptError as error:
        return _error(request, error.code, locale)
    context = {
        "earned": _points(result.earned_points),
        "maximum": _points(result.max_points),
        "percentage": result.percentage_display,
        "correct_count": result.correct_count,
    }
    return _respond(request, "public/_result.html", context, locale)
