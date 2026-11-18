"""Refusals of the play views: codes with status and text, the error page or fragment, the limit."""

import time
from collections.abc import Mapping
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext_lazy as _

from app.api import rate_limit
from app.api.rendering import (
    page,
)

STATUS = {
    "invalid_request": 400,
    "invalid_answer": 400,
    "invalid_token": 403,
    "not_found": 404,
    "run_closed": 409,
    "run_not_started": 409,
    "already_submitted": 409,
    "submission_key_used": 409,
    "attempt_switched": 409,
    "attempt_expired": 410,
    "attempt_gone": 410,
    "revision_unavailable": 503,
    "reveal_not_allowed": 403,
    "not_in_attempt": 403,
    "test_link_ended": 410,
    "already_played": 409,
    "attempts_used": 409,
    "already_passed": 409,
    "time_is_up": 410,
    "attempt_closed": 409,
    "name_required": 422,
    "name_too_long": 422,
    "email_required": 422,
    "email_invalid": 422,
    "name_taken": 409,
    "code_required": 403,
    "not_in_run": 403,
    "resume_off": 409,
    "rate_limited": 429,
}


MESSAGES = {
    "invalid_request": _("The form could not be read. Please try again."),
    "invalid_answer": _("An answer could not be read. Please check your answers."),
    "invalid_token": _("This attempt is not valid. Please start again."),
    "not_found": _("This attempt does not exist."),
    "run_closed": _("This run has ended."),
    "run_not_started": _("This quiz has not started yet."),
    "already_submitted": _("This attempt has already been submitted."),
    "submission_key_used": _("This attempt has already been submitted."),
    "attempt_switched": _(
        "This attempt was replaced by a newer version of the quiz. Please reload the page."
    ),
    "attempt_expired": _("The time for this attempt has run out."),
    "attempt_gone": _("This attempt has already been submitted or has ended."),
    "revision_unavailable": _("This quiz is temporarily unavailable."),
    "reveal_not_allowed": _("This quiz does not show answers now."),
    "not_in_attempt": _("This question is not part of your attempt."),
    "test_link_ended": _("This test has ended."),
    "already_played": _("You have already played this run in this browser."),
    "attempts_used": _("You have used all %(count)s attempts."),
    "already_passed": _("You have already passed."),
    "time_is_up": _("Time is up for your attempt. It cannot be started again."),
    "attempt_closed": _("This attempt was closed because you started again."),
    "name_required": _("Please enter your name."),
    "name_too_long": _("The name can have at most 40 characters."),
    "email_required": _("Please enter your e-mail."),
    "email_invalid": _("The e-mail address does not look right."),
    "name_taken": _("This name is already used in this run. Please choose another one."),
    "code_required": _("This run needs an access code. Reload the page and enter it."),
    "not_in_run": _("This attempt belongs to another run."),
    "resume_off": _("This quiz does not let you continue an attempt on this device."),
    "rate_limited": _("Too many requests from this address. Please try again in a minute."),
}


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def message_context(
    code: str, locale: str, extra: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The message of a refusal in the participant's language, with its extra lines."""
    context: dict[str, Any] = {"message": MESSAGES[code], **(extra or {})}
    if code in COUNTED_MESSAGES:  # the text names a number, so it must be given one
        with translation.override(locale):
            context["message"] = str(MESSAGES[code]) % {"count": context["count"]}
    return context


# Messages whose text holds %(count)s.
COUNTED_MESSAGES = frozenset({"attempts_used"})


def _error(
    request: HttpRequest, code: str, locale: str, extra: Mapping[str, Any] | None = None
) -> HttpResponse:
    context = message_context(code, locale, extra)
    if _is_htmx(request):
        return _message_fragment(context, locale, STATUS[code])
    context |= {"partial": "public/_error_page.html"}
    return page(request, "public/play.html", context, locale, status=STATUS[code])


def _limited(request: HttpRequest, bucket: str, token: str | None = None) -> HttpResponse | None:
    """The limit is the first thing a view does: before a lookup, a row or a cookie.

    Without a token every request counts. With one (the attempt of `submit`), a repeat of the same
    attempt passes without counting again, but only up to `rate_limit.FREE_REPEATS` times within the
    window of its first counted send (ADR-0058, TD-091).
    """
    ip, now = rate_limit.client_ip(request), time.monotonic()
    if token is None:
        allowed = rate_limit.try_acquire(bucket, ip, now)
    else:
        allowed = rate_limit.try_acquire_once(bucket, ip, token, now)
    if not allowed:
        response = _error(request, "rate_limited", request.locale)  # type: ignore[attr-defined]
        response["Retry-After"] = rate_limit.retry_after()
        return response
    return None


def _message_fragment(context: dict[str, Any], locale: str, status: int) -> HttpResponse:
    translation.activate(locale)
    response = HttpResponse(render_to_string("public/_error.html", context), status=status)
    response["HX-Retarget"] = "#play-message"
    return response
