"""Start and submit. Forms work with HTMX and without it; the same service decides everything."""

import contextlib
import re
import secrets
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.conf import settings as django_settings
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from app.api import i18n, pass_mark, rate_limit, scoreboard
from app.api.play_errors import (
    COUNTED_MESSAGES,
    MESSAGES,
    STATUS,
    _error,
    _is_htmx,
    _limited,
    _message_fragment,
    message_context,
)
from app.api.rendering import (
    delete_images,
    flow_options,
    identity_context,
    identity_form,
    media_storage,
    mode_bar_of,
    page,
    question_html,
    question_settings,
    result_sources,
    reveal_context,
)
from app.contracts import AFTER_PASS, ASK_WHEN, LOCAL_RESUME, MAX_PHOTO_BYTES, ImageRefused
from app.domain import (
    access_codes,
    attempts,
    data_policy,
    grading,
    participants,
    results,
    reveal,
    rewards,
    tokens,
    visibility,
)
from app.domain.models import Attempt, Participant, QuizRun
from app.kernel import registry

KEY = re.compile(r"[A-Za-z0-9_-]{8,64}")
SUBMIT_ROUTE = re.compile(r"/a/([0-9a-fA-F-]{36})/submit")
IDENTITY_CODES = ("name_required", "name_too_long", "email_required", "email_invalid", "name_taken")
DROP_COPY = frozenset(
    {
        "not_in_run",
        "already_submitted",
        "attempt_closed",
        "attempt_gone",
        "attempt_expired",
        "run_closed",
        "resume_off",
        "invalid_token",
        "not_found",
        "test_link_ended",
    }
)


def _no_store(response: HttpResponse) -> HttpResponse:
    """A page giving the typed name or e-mail back is not for a cache or the back button."""
    response["Cache-Control"] = "private, no-store"
    return response


def _respond(
    request: HttpRequest, partial: str, context: dict[str, Any], locale: str
) -> HttpResponse:
    if _is_htmx(request):
        translation.activate(locale)
        return HttpResponse(render_to_string(partial, context | {"locale": locale}, request))
    return page(request, "public/play.html", context | {"partial": partial}, locale)


def start_refusal(
    run: QuizRun, participant: Participant | None, locale: str
) -> dict[str, Any] | None:
    """The message a start would meet, for a page that should not offer it; None when it is open."""
    decision = participants.start_decision(run, participant)
    if decision == "played":
        code, extra = played_result(run, participant, locale)
        return message_context(code, locale, extra)
    if decision == "time_up":
        return message_context("time_is_up", locale)
    return None


def accepts_upload(request: HttpRequest) -> bool:
    """Whether this request may carry a photo. The body stays unread (ADR-0047).

    An attempt already finished is let through too, as a repeat after a lost answer deserves its
    result. So is a late one for a while, as it deserves to hear why. Nothing of these is stored.
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
        closed_at = attempt.run.closed_at
        if closed_at is None or timezone.now() > closed_at + attempts.LATE_UPLOAD_WINDOW:
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


def received_time(request: HttpRequest) -> datetime:
    """When the whole request arrived (ADR-0025). A body still on its way must not count as here.

    Django reads the body lazily, so the clock is read after asking for it. A body it refuses gets
    its answer from the code that needs the form.
    """
    with contextlib.suppress(RequestDataTooBig, TooManyFieldsSent):
        request.POST  # noqa: B018  # the read is the point
    return timezone.now()


def time_context(attempt: Attempt) -> dict[str, Any]:
    return {
        "time_left": attempts.time_left(attempt),
        "time_url": reverse("attempt_time", args=[attempt.id]),
    }


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


def _play_context(
    run: QuizRun,
    started: attempts.StartedAttempt,
    questions: list[dict[str, Any]],
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    """The questions page, the same for a new attempt and for one that carries on."""
    attempt = started.attempt
    return {
        "branding_quiz": run.quiz,
        "mode_bar": mode_bar_of(run),
        "attempt": attempt,
        "attempt_token": started.token,
        "submission_key": started.submission_key,
        "questions": questions,
        "flow": flow_options(attempts.flow_of(attempt)),
        "uploads": uploads(attempt),
        "identity": identity,
        "resumable": attempts.flow_of(attempt).get(LOCAL_RESUME) == "on",
        "copy_expires": attempts.copy_expiry(attempt).isoformat(),
        "run_id": run.id,
        **time_context(attempt),
    }


@csrf_exempt
@require_POST
def start(request: HttpRequest, run_id: UUID) -> HttpResponse:
    if (refused := _limited(request, "start")) is not None:
        return refused
    run = QuizRun.all_kinds.filter(pk=run_id).select_related("current_revision").first()
    if run is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = run.current_revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    if needs_code(request, run):
        return _error(request, "code_required", locale)  # before any name check or new row
    key = ""
    fresh = False
    participant = None
    if participants.needs_participant(run):
        key = request.COOKIES.get(participants.cookie_name(run), "")
        if not key:
            key, fresh = secrets.token_urlsafe(32), True
    rules = participants.rules_of(run)
    identity = _identity_at_start(request, run, rules, key)
    if isinstance(identity, str):
        return _error(request, identity, locale)
    try:
        if key:
            participant = participants.find_or_create(run, key)
        started = attempts.start(
            run,
            participant=participant,
            unlocked=access_codes.is_unlocked(
                run, request.COOKIES.get(access_codes.cookie_name(run))
            ),
        )
        questions = _questions(started.attempt, locale)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        if error.code == "already_played":
            code, extra = played_result(run, participant, locale)
            return _error(request, code, locale, extra)
        return _error(request, error.code, locale)
    context = _play_context(
        run,
        started,
        questions,
        identity_context(rules, identity.name, identity.email or "")
        if identity
        else identity_context(rules),
    )
    response = _respond(request, "public/_questions.html", context, locale)
    if identity:
        _no_store(response)
    if fresh:
        _set_cookie(response, participants.cookie_name(run), key, participants.COOKIE_MAX_AGE)
    return response


@csrf_exempt
@require_POST
def resume(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """The attempt a browser kept a copy of. The token comes in the body, never in the address."""
    run = QuizRun.all_kinds.filter(pk=run_id).select_related("current_revision").first()
    if run is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    snapshot = run.current_revision.snapshot_json
    locale = _locale(request, snapshot["locales"], snapshot["default_locale"])
    if locale is None:
        return _error(request, "invalid_request", snapshot["default_locale"])
    try:
        attempt_id = UUID(request.POST.get("attempt_id", ""))
    except ValueError:
        return _error(request, "invalid_request", locale)
    try:
        started = attempts.resume_by_token(run, attempt_id, request.POST.get("attempt_token", ""))
        questions = _questions(started.attempt, locale)
    except registry.UnknownPort:
        return _error(request, "revision_unavailable", locale)
    except attempts.AttemptError as error:
        response = _error(request, error.code, locale)
        if error.code in DROP_COPY:
            response["X-Kvz-Drop-Copy"] = "1"
        return response
    rules = participants.rules_of(run)
    # The name typed before the start is not kept, so the fields come back at the end.
    context = _play_context(run, started, questions, identity_context(rules, refused=True)) | {
        "resume": True
    }
    return _no_store(_respond(request, "public/_questions.html", context, locale))


def needs_code(request: HttpRequest, run: QuizRun) -> bool:
    """The code form comes first, unless the code was entered or an attempt is already begun."""
    if run.kind == QuizRun.Kind.TEST or access_codes.is_unlocked(
        run, request.COOKIES.get(access_codes.cookie_name(run))
    ):
        return False
    key = request.COOKIES.get(participants.cookie_name(run), "")
    return not participants.can_resume(run, participants.find(run, key))


def _set_cookie(response: HttpResponse, name: str, value: str, max_age: int) -> None:
    """The flags of every cookie a participant gets."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=not django_settings.DEBUG,
        samesite="Lax",
        path="/",
    )


@require_POST
def enter_code(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """The code is read from the form only: not from the address, a log or the session."""
    from app.api import public  # public imports MESSAGES from here

    run = (
        QuizRun.all_kinds.filter(pk=run_id, quiz__archived_at__isnull=True)
        .select_related("quiz", "current_revision")
        .first()
    )
    if run is None:
        return _error(request, "not_found", request.locale)  # type: ignore[attr-defined]
    if run.kind == QuizRun.Kind.TEST:
        return redirect(reverse("test_link", args=[run.test_link.token]))
    if not run.access_code_hash:  # nothing to guess, so nothing to count
        return redirect(reverse("quiz_run", args=[run.quiz.slug, run.id]))
    ip = rate_limit.client_ip(request)
    if not rate_limit.try_acquire("code", ip, time.monotonic()):
        response = public.quiz_page(
            request,
            run,
            code_error=_("Too many wrong codes. Please try again in a minute."),
            status=429,
        )
        response["Retry-After"] = rate_limit.retry_after()
        return response
    if not access_codes.matches(run, request.POST.get("code", "")):
        return public.quiz_page(
            request,
            run,
            code_error=_("The access code is not right. Please try again."),
            status=403,
        )
    rate_limit.release("code", ip)  # only wrong guesses keep their slot
    response = redirect(reverse("quiz_run", args=[run.quiz.slug, run.id]))
    _set_cookie(
        response,
        access_codes.cookie_name(run),
        access_codes.unlock_token(run),
        access_codes.COOKIE_MAX_AGE,
    )
    return response


def _identity_at_start(
    request: HttpRequest, run: QuizRun, rules: Mapping[str, str], key: str
) -> participants.Identity | str | None:
    """The values asked before the start, checked here. A refusal comes back as its code."""
    if rules.get(ASK_WHEN, "end") != "start" or identity_context(rules) is None:
        return None
    try:
        identity = participants.read_identity(
            rules,
            request.POST.get("participant_name", ""),
            request.POST.get("participant_email", ""),
            automatic=False,
        )
    except attempts.AttemptError as error:
        return error.code
    # Early feedback only; the binding check is at submission.
    if participants.name_is_taken(run, identity.name, exclude=participants.find(run, key)):
        return "name_taken"
    return identity


def rewards_shown(attempt: Attempt, locale: str) -> list[rewards.ShownReward]:
    """The participant's own rewards for a result page; nothing for an attempt without one."""
    if attempt.participant_id is None:
        return []
    participant = (
        Participant.objects.filter(pk=attempt.participant_id).select_related("run__quiz").first()
    )
    return rewards.shown(participant, locale)


def played_result(
    run: QuizRun, participant: Participant | None, locale: str
) -> tuple[str, dict[str, Any]]:
    """Which refusal this is, and its extra lines: the person's own kept result when there is one.

    A pass that ends the test comes before the limit; without either it is "one per browser".
    """
    found = results.kept(participant) if participant is not None else None
    rules = participants.rules_of(run)
    code = "already_played"
    extra: dict[str, Any] = {"one_per_browser": True}
    if results.kept_passed(found, run) is True and rules.get(AFTER_PASS) == "stop":
        code, extra = "already_passed", {}
    elif participants.attempts_left(run, participant) == 0:
        code, extra = "attempts_used", {"count": participants.limit_of(rules)}
    if found is not None:
        extra["result_url"] = reverse("result", args=[tokens.issue_result(found.attempt.id)])
        line = pass_mark.line(
            found.figures.score,
            found.figures.max_score,
            found.waiting,
            results.pass_mark(run),
            locale,
        )
        if line:
            extra["result_line"] = line
    elif participant is not None:  # nothing scored: still the link to the latest finished one
        latest = (
            Attempt.objects.filter(participant=participant, status__in=Attempt.FINISHED)
            .order_by("-submitted_at")
            .first()
        )
        if latest is not None:
            extra["result_url"] = reverse("result", args=[tokens.issue_result(latest.id)])
    return code, extra


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
    lenient: bool = False,
    stored: list[str] | None = None,
) -> list[str]:
    """Hands each file to `read` for an asset id. Returns the ids; a refusal leaves none.

    `lenient` is for the automatic submission: a refused file is left out and the rest stay.
    A caller that passes `stored` owns that list and finds every id written in it, also when
    this raises anything but a refusal, so it can remove them.
    """
    stored = [] if stored is None else stored
    try:
        for question in attempts.questions_of(attempt):
            for field in attempts.file_fields(question):
                upload = request.FILES.get(f"{question['id']}:{field}")
                if upload is None:
                    continue
                try:
                    if upload.size > MAX_PHOTO_BYTES:
                        raise ImageRefused(str(_("A photo can be at most 15 MB.")))
                    asset = read(upload.read(), stored)
                except ImageRefused:
                    if lenient:
                        continue
                    raise
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


def _identity_of_form(
    request: HttpRequest, attempt: Attempt, refused: bool = False
) -> dict[str, Any] | None:
    return identity_context(
        participants.rules_of(attempt.run),
        request.POST.get("participant_name", ""),
        request.POST.get("participant_email", ""),
        refused,
    )


def _identity_refused(
    request: HttpRequest, attempt: Attempt, locale: str, code: str
) -> HttpResponse:
    """The answers and the fields stay; only the message is placed next to the fields."""
    identity = _identity_of_form(request, attempt, refused=True)
    if _is_htmx(request):
        translation.activate(locale)
        body = render_to_string(
            "public/_identity_error.html", {"message": MESSAGES[code], "identity": identity}
        )
        response = HttpResponse(body, status=STATUS[code])
        response["HX-Retarget"] = "#identity-error"
        response["HX-Reswap"] = "innerHTML"
        return _no_store(response)
    return _no_store(
        _try_again(request, attempt, locale, identity_message=MESSAGES[code], status=STATUS[code])
    )


def _try_again(
    request: HttpRequest,
    attempt: Attempt,
    locale: str,
    message: Any = None,
    identity_message: Any = None,
    status: int | None = None,
) -> HttpResponse:
    """Without a script the page is replaced, so the form comes back with the answers in it."""
    answers = _answers(request)
    without_files(attempt, answers)
    context = {
        "branding_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "attempt": attempt,
        "attempt_token": request.POST.get("attempt_token", ""),
        "submission_key": request.POST.get("submission_key", ""),
        "questions": _questions(attempt, locale, answers),
        "flow": flow_options(attempts.flow_of(attempt)),
        "uploads": uploads(attempt),
        "partial": "public/_questions.html",
        **time_context(attempt),
        "play_message": "" if identity_message else message or MESSAGES["invalid_answer"],
        "identity": _identity_of_form(request, attempt, refused=bool(identity_message)),
        "identity_message": identity_message,
    }
    return page(
        request, "public/play.html", context, locale, status=status or STATUS["invalid_answer"]
    )


def _revealed(attempt: Attempt, answers: Mapping[str, Any], locale: str) -> list[dict[str, Any]]:
    """After each question also lists them here, because a page without a script saw nothing yet.

    A repeated submission may carry anything, and its score is already stored.
    """
    flow = attempts.flow_of(attempt)
    if not reveal.shows_answers(attempt, timezone.now()):
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


def _result_link(
    attempt: Attempt, result: attempts.AttemptResult, asks_identity: bool = False
) -> str | None:
    if data_policy.is_stateless(data_policy.profile_of_attempt(attempt)):
        return None  # nothing is stored to show again
    if not result.pending and not asks_identity and not visibility.has_more_to_see(attempt):
        return None
    return reverse("result", args=[tokens.issue_result(attempt.id)])


@csrf_exempt
@require_POST
def submit(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    if (refused := _limited(request, "submit")) is not None:
        return refused
    received_at = received_time(request)
    automatic = request.POST.get("auto_submit") == "1"
    attempt = Attempt.objects.filter(pk=attempt_id).select_related("revision", "run").first()
    if attempt is None:
        code = attempts.missing_code(attempt_id, request.POST.get("attempt_token", ""))
        return _error(request, code, request.locale)  # type: ignore[attr-defined]
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
    identity = None
    try:
        if attempt.status == Attempt.Status.IN_PROGRESS and attempt.participant_id is not None:
            identity = participants.read_identity(
                participants.rules_of(attempt.run),
                request.POST.get("participant_name", ""),
                request.POST.get("participant_email", ""),
                automatic=automatic,
            )
        without_files(attempt, answers)
        if request.FILES and attempt.status == Attempt.Status.IN_PROGRESS:
            attempts.verify_open(attempt_id, token, received_at)
            with translation.override(locale):
                with_files(
                    request,
                    attempt,
                    answers,
                    _store_photo(attempt),
                    lenient=automatic,
                    stored=stored,
                )
        result = attempts.submit(
            attempt_id,
            token,
            answers,
            key,
            received_at=received_at,
            lenient=automatic,
            identity=identity,
        )
    except ImageRefused as error:
        return _refused(request, attempt, locale, error)
    except attempts.AttemptError as error:
        delete_images(stored)
        if error.code in IDENTITY_CODES:
            return _identity_refused(request, attempt, locale, error.code)
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
    form = identity_form(attempt)
    link = _result_link(attempt, result, form is not None)
    context = {
        "branding_quiz": attempt.run.quiz,
        "mode_bar": mode_bar_of(attempt.run),
        "revealed": revealed,
        "earned": result.earned_points,
        "maximum": result.max_points,
        "sources": result_sources(attempts.questions_of(attempt), attempt.run.quiz, locale),
        "percentage": result.percentage_display,
        "correct_count": result.correct_count,
        "pending": result.pending,
        "time_ran_out": automatic,
        "identity_form": form,
        "result_link": link,
        "after_close_note": reveal.after_close_note(attempt, locale)
        if link or attempt.run.kind == QuizRun.Kind.TEST
        else "",
        "stateless": data_policy.is_stateless(data_policy.profile_of_attempt(attempt)),
        "remember_quiz": attempt.run.quiz.slug if attempt.run.kind == QuizRun.Kind.NORMAL else "",
        "rewards": rewards_shown(attempt, locale),
        **scoreboard.place_context(attempt),
        **pass_mark.context(
            attempt,
            locale,
            score=result.earned_points,
            maximum=result.max_points,
            pending=result.pending,
        ),
    }
    response = _respond(request, "public/_result.html", context, locale)
    return _no_store(response) if form is not None else response


@csrf_exempt
@require_POST
def attempt_time(request: HttpRequest, attempt_id: UUID) -> HttpResponse:
    """Only the seconds left, so a moved deadline reaches an open page. Nothing is written."""
    try:
        left = attempts.remaining(attempt_id, request.POST.get("attempt_token", ""))
    except attempts.AttemptError as error:
        return JsonResponse({"error": error.code}, status=STATUS[error.code])
    return JsonResponse({"remaining": left})


# Names that moved to the split modules and are still imported from here (not a star-import list).
__all__ = [
    "COUNTED_MESSAGES",
    "MESSAGES",
    "STATUS",
    "_error",
    "_is_htmx",
    "_limited",
    "_message_fragment",
    "message_context",
]
