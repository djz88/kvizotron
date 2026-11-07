"""Quiz list and editor. Rules live in app.domain.authoring and in question type plugins."""

import secrets
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from functools import wraps
from typing import Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from markupsafe import Markup

from app.api import rendering
from app.api.admin_auth import admin_required
from app.api.admin_forms import (
    DuplicateQuizForm,
    QuestionCommonForm,
    QuizBehaviourForm,
    QuizContentForm,
    QuizForm,
    setting_initial,
)
from app.api.admin_workspace import image_check, quiz_title, workspace
from app.api.rendering import media_storage, page, question_label, with_media_urls
from app.contracts import (
    EXTERNAL_IMAGE_MODE,
    IMAGE_MODE_COPY,
    AdminFormError,
    ImageAddressInvalid,
    ImageRefused,
    MediaStorageProvider,
    QuestionTypePlugin,
    ScoringStrategyPlugin,
)
from app.domain import (
    authoring,
    banks,
    external_images,
    questions,
    quiz_state,
    requirements,
    revision_diff,
    selection,
    settings,
)
from app.domain.models import Quiz
from app.kernel import registry

FETCHES_SECONDS = 25.0  # all address fetches of one save together


def _archived_message() -> str:
    return _("This quiz is archived. Restore it to change it.")


@admin_required
def quiz_list(request: HttpRequest) -> HttpResponse:
    show_archived = request.GET.get("archived") == "1"
    quizzes = [
        {"id": quiz.id, "title": quiz_title(quiz), "slug": quiz.slug, "state": quiz_state.of(quiz)}
        for quiz in Quiz.objects.filter(archived_at__isnull=not show_archived).order_by(
            "-created_at"
        )
    ]
    context = {
        "quizzes": quizzes,
        "show_archived": show_archived,
        "can_import": rendering.can_import(),
    }
    return page(request, "admin/quiz_list.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def quiz_new(request: HttpRequest) -> HttpResponse:
    form = QuizForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                quiz = form.apply_to(Quiz())
        except IntegrityError:  # another admin, or a double click, took the identifier first
            form.add_error("slug", _("Another quiz already uses this identifier."))
        else:
            return redirect("admin_quiz_edit", quiz.id)
    return page(request, "admin/quiz_form.html", {"form": form}, request.locale)  # type: ignore[attr-defined]


def _free_slug(quiz: Quiz) -> str:
    suffix = "-copy"
    candidate = f"{quiz.slug[: 80 - len(suffix)]}{suffix}"
    number = 2
    while Quiz.objects.filter(slug=candidate).exists():
        tail = f"{suffix}-{number}"
        candidate = f"{quiz.slug[: 80 - len(tail)]}{tail}"
        number += 1
    return candidate


def _type_label(type_id: str) -> str:
    """A type that is no longer installed still has to appear in the list."""
    try:
        plugin = registry.get("question_type", type_id, include_disabled=True)
    except LookupError:
        return type_id
    return cast(QuestionTypePlugin, plugin).label()


def _add_menu() -> list[dict[str, str]]:
    items = []
    for type_id in registry.keys("question_type"):
        plugin = cast(QuestionTypePlugin, registry.get("question_type", type_id))
        items.append({"query": f"type={type_id}", "label": plugin.label()})
        items += [
            {"query": f"type={type_id}&preset={preset['id']}", "label": preset["label"]}
            for preset in plugin.presets()
        ]
    return items


def _question_row(number: int, question: Mapping[str, Any], quiz: Quiz) -> dict[str, Any]:
    return {
        "kind": "question",
        "id": question["id"],
        "number": number,
        "label": question_label(question, quiz.default_locale),
        "type": _type_label(question["type"]),
        "points": question.get("settings", {}).get("points"),
        "to_fix": questions.locales_to_fix(question, quiz.supported_locales),
        "no_copy": questions.has_image_without_copy(question),
    }


def _draw_row(row: Mapping[str, Any], quiz: Quiz) -> dict[str, Any]:
    usable, total = banks.usable_count(row, quiz.supported_locales)
    return {
        **row,
        "kind": "draw",
        "usable": usable,
        "total": total,
        "bank_missing": not banks.exists(row["bank_id"]),
    }


def edit_page(
    request: HttpRequest,
    quiz: Quiz,
    run_error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    context = workspace(quiz, "edit", run_error)
    numbered = list(enumerate(authoring.editable_questions(quiz), start=1))
    context["rows"] = [
        _draw_row(item, quiz) if kind == "draw" else _question_row(item[0], item[1], quiz)
        for kind, item in selection.layout(numbered, authoring.editable_draws(quiz))
    ]
    context["question_types"] = _add_menu()
    return page(
        request,
        "admin/quiz_edit.html",
        context,
        request.locale,  # type: ignore[attr-defined]
        status=status,
    )


def settings_page(
    request: HttpRequest,
    quiz: Quiz,
    content_form: QuizContentForm | None = None,
    behaviour_form: QuizBehaviourForm | None = None,
    run_error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    context = workspace(quiz, "settings", run_error)
    context["content_form"] = content_form or QuizContentForm(quiz=quiz)
    context["behaviour_form"] = behaviour_form or QuizBehaviourForm(quiz=quiz)
    context["flow_conflict"] = settings.flow(quiz).conflict
    context["visibility_conflict"] = settings.visibility_conflict(quiz)
    return page(
        request,
        "admin/quiz_settings.html",
        context,
        request.locale,  # type: ignore[attr-defined]
        status=status,
    )


def not_archived(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """An archived quiz is read-only; the page says what to do instead of failing later."""

    @wraps(view)
    def checked(request: HttpRequest, quiz_id: UUID, *args: Any, **kwargs: Any) -> HttpResponse:
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        if quiz.archived_at is None:
            return view(request, quiz_id, *args, **kwargs)
        return edit_page(request, quiz, run_error=_archived_message(), status=409)

    return checked


@admin_required
def quiz_edit(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """GET is the questions tab; POST saves what the settings tab's first part holds."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method != "POST":
        return edit_page(request, quiz)
    if quiz.archived_at is not None:
        return edit_page(request, quiz, run_error=_archived_message(), status=409)
    form = QuizContentForm(request.POST, quiz=quiz)
    if not form.is_valid():
        return settings_page(request, quiz, content_form=form)
    form.apply_to(quiz)
    if form.has_changed():
        authoring.get_draft(quiz)  # so that the change can be published
    return redirect("admin_quiz_settings", quiz.id)


@admin_required
@require_POST
def image_check_view(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """After the page, so it never waits. The result replaces the warning (ADR-0043)."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    addresses = external_images.addresses_of(quiz)
    storage = media_storage()
    if storage and addresses:
        storage.check_addresses(addresses, allow_internal=settings.internal_addresses_allowed())
    context = {"image_check": image_check(quiz)}
    return page(request, "admin/_image_warning.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def quiz_settings(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """What applies immediately. A behaviour setting is not part of a revision."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method != "POST":
        return settings_page(request, quiz)
    if quiz.archived_at is not None:
        return settings_page(request, quiz, run_error=_archived_message(), status=409)
    form = QuizBehaviourForm(request.POST, quiz=quiz)
    if not form.is_valid():
        return settings_page(request, quiz, behaviour_form=form)
    try:
        with transaction.atomic():
            form.apply_to(quiz)
    except IntegrityError:  # another admin took the identifier at the same moment
        form.add_error("slug", _("Another quiz already uses this identifier."))
        return settings_page(request, quiz, behaviour_form=form)
    for key in settings.keys_for("quiz"):
        value = form.cleaned_data[key]
        if (value or None) != settings.quiz_override(key, quiz):
            settings.set_override(key, quiz, value or None, admin_id=str(request.user.pk))
    return redirect("admin_quiz_settings", quiz.id)


def _enabled_plugin(type_id: str) -> QuestionTypePlugin:
    if type_id not in registry.keys("question_type"):
        raise Http404
    return cast(QuestionTypePlugin, registry.get("question_type", type_id))


def _strategies(plugin: QuestionTypePlugin) -> list[tuple[str, str]]:
    offered = []
    for strategy_id in plugin.available_scoring_strategies():
        if strategy_id in registry.keys("scoring_strategy"):
            strategy = cast(ScoringStrategyPlugin, registry.get("scoring_strategy", strategy_id))
            offered.append((strategy_id, strategy.label()))
    return offered


def _common_form(
    plugin: QuestionTypePlugin,
    question: Mapping[str, Any] | None,
    locales: Sequence[str],
    quiz: Quiz,
) -> QuestionCommonForm:
    initial: dict[str, Any] = {"points": questions.DEFAULT_POINTS}
    if question is not None:
        initial = {
            "points": question["settings"].get("points"),
            "scoring": question["scoring"],
            "sources": "\n".join(question.get("sources", [])),
            **setting_initial(question),
            **{
                f"explanation_{locale}": text
                for locale, text in question.get("explanation", {}).items()
            },
        }
    return QuestionCommonForm(
        initial=initial, strategies=_strategies(plugin), locales=locales, plugin=plugin, quiz=quiz
    )


def _question_page(
    request: HttpRequest,
    quiz: Quiz,
    plugin: QuestionTypePlugin,
    config: Any,
    common_form: QuestionCommonForm,
    form_key: str | None,
    error: str | None = None,
) -> HttpResponse:
    context = {
        "quiz": quiz,
        "type_label": plugin.label(),
        "editor": Markup(  # noqa: S704  # the plugin escapes through its own template
            plugin.render_admin(with_media_urls(config, keep_asset=True), quiz.supported_locales)
        ),
        "common_form": common_form,
        "form_key": form_key,
        "error": error,
        "back_url": reverse("admin_quiz_edit", args=[quiz.id]),
        "requirements": requirements.unmet(quiz, requirements.of_type(plugin.id)),
        "here": request.get_full_path(),
    }
    return page(request, "admin/question_form.html", context, request.locale)  # type: ignore[attr-defined]


def _fetch_addresses(
    form: dict[str, list[Any]],
    files: Mapping[str, Any],
    storage: MediaStorageProvider | None,
    quiz: Quiz | None,
) -> list[str]:
    """After files, because a file wins. Returns what to tell the admin (ADR-0043).

    All fetches share one limit, so several dead addresses cannot hold the request for long. An
    address that fails stays without a copy only where the image would load from it anyway.
    """
    refused: list[str] = []
    deadline = time.monotonic() + FETCHES_SECONDS
    submitted = form.get(f"setting_{EXTERNAL_IMAGE_MODE}", [""])[-1]
    mode = settings.image_mode(quiz, {"settings": {EXTERNAL_IMAGE_MODE: submitted}})
    addresses = [n for n in form if n.endswith("_source") and not n.endswith("_kept_source")]
    for field in addresses:
        name = field.removesuffix("_source")
        address = str(form[field][-1]).strip()
        form[field] = [address]
        if f"{name}_refused" in form:
            continue
        if not address or name in files or f"{name}_remove" in form:
            del form[field]
            continue
        if storage is None:
            refused.append(_("Images cannot be stored on this installation."))
            continue
        try:
            storage.check_image_address(address)
            if form.get(f"{name}_kept_source", [""])[-1] == address and f"{name}_asset" in form:
                continue
            form.pop(f"{name}_asset", None)
            form[f"{name}_asset"] = [
                storage.fetch_image(
                    address, allow_internal=settings.internal_addresses_allowed(), deadline=deadline
                )
            ]
        except ImageAddressInvalid as error:
            refused.append(f"{address}: {error}")
            form[f"{name}_refused"] = ["1"]
        except ImageRefused as error:
            if mode == IMAGE_MODE_COPY:
                refused.append(f"{address}: {error}")
                form[f"{name}_refused"] = ["1"]
    return refused


def _form_with_uploads(
    request: HttpRequest, quiz: Quiz | None = None
) -> tuple[dict[str, list[Any]], list[str]]:
    """Files go to storage first, so a plugin sees only ids, and a failed form keeps them."""
    form: dict[str, list[Any]] = dict(request.POST.lists())
    storage = media_storage()
    for name in [name for name in form if name.endswith("_asset")]:
        if storage is None or not storage.exists(form[name][-1]):
            del form[name]
    refused = []
    for name, upload in request.FILES.items():
        if storage is None:
            refused.append(_("Images cannot be stored on this installation."))
            continue
        try:
            form[f"{name}_asset"] = [storage.store_image(upload.read())]
        except ImageRefused as error:
            refused.append(f"{upload.name}: {error}")
            form[f"{name}_refused"] = ["1"]
        else:
            form.pop(f"{name}_remove", None)
    return form, refused + _fetch_addresses(form, request.FILES, storage, quiz)


def read_question_form(
    request: HttpRequest,
    plugin: QuestionTypePlugin,
    locales: Sequence[str],
    current: Any,
    quiz: Quiz | None = None,
) -> tuple[Any, str | None]:
    """The definition as far as it could be read, and what to tell the admin if anything."""
    form, refused = _form_with_uploads(request, quiz)
    try:
        config = plugin.parse_admin(form, locales)
    except AdminFormError as error:
        return error.config, " ".join([*refused, str(error)])
    except ValueError as error:
        return current, " ".join([*refused, str(error)])
    return config, " ".join(refused) or None


def _save_question(
    request: HttpRequest,
    quiz: Quiz,
    plugin: QuestionTypePlugin,
    question_id: str | None,
    current: Any,
) -> HttpResponse:
    common = QuestionCommonForm(
        request.POST,
        strategies=_strategies(plugin),
        locales=quiz.supported_locales,
        plugin=plugin,
        quiz=quiz,
    )
    key = request.POST.get("form_key", "") if question_id is None else None
    config, message = read_question_form(request, plugin, quiz.supported_locales, current, quiz)
    if message or not common.is_valid():
        return _question_page(request, quiz, plugin, config, common, key, message)
    authoring.save_question(
        quiz,
        question_id,
        plugin.id,
        config,
        points=common.cleaned_data["points"],
        scoring=common.cleaned_data["scoring"] or None,
        sources=common.cleaned_data["sources"],
        explanation=common.explanation(),
        new_id=str(uuid.uuid5(quiz.id, key)) if key else None,
        setting_values=common.setting_values(),
    )
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
def question_new(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    plugin = _enabled_plugin(request.GET.get("type", ""))
    if request.method == "POST":
        return _save_question(request, quiz, plugin, None, {})
    config = plugin.initial(request.GET.get("preset", ""), quiz.supported_locales)
    form_key = secrets.token_urlsafe(16)
    common = _common_form(plugin, None, quiz.supported_locales, quiz)
    return _question_page(request, quiz, plugin, config, common, form_key)


def _existing_question(quiz: Quiz, question_id: str) -> dict[str, Any]:
    for question in authoring.editable_questions(quiz):
        if question["id"] == question_id:
            return question
    raise Http404


@admin_required
@not_archived
def question_edit(request: HttpRequest, quiz_id: UUID, question_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    question = _existing_question(quiz, question_id)
    plugin = _enabled_plugin(question["type"])
    if request.method == "POST":
        return _save_question(request, quiz, plugin, question_id, question["definition"])
    common = _common_form(plugin, question, quiz.supported_locales, quiz)
    return _question_page(request, quiz, plugin, question["definition"], common, None)


@admin_required
@not_archived
@require_POST
def question_delete(request: HttpRequest, quiz_id: UUID, question_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    _existing_question(quiz, question_id)
    authoring.delete_question(quiz, question_id)
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
@require_POST
def requirement_use(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    """Offered next to a requirement; the type may not be in the quiz yet, on a new question."""
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    requirement = requirements.named(request.POST.get("key", ""), quiz)
    if requirement is None:
        return HttpResponseBadRequest()
    requirements.apply(requirement, quiz, admin_id=str(request.user.pk))
    back = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(back)
    return redirect("admin_quiz_edit", quiz.id)


def problem_text(problem: authoring.Problem) -> str:
    if problem.code == "no_questions":
        return _("The quiz has no questions.")
    if problem.code == "no_changes":
        return _("There is nothing new to publish.")
    if problem.code == "title_missing":
        return _("The title is missing in language %(locale)s.") % {"locale": problem.locale}
    if problem.code == "description_missing":
        return _("The description is missing in language %(locale)s.") % {"locale": problem.locale}
    if problem.code == "explanation_missing":
        return _("Question %(number)s: the explanation is missing in language %(locale)s.") % {
            "number": problem.question_no,
            "locale": problem.locale,
        }
    if problem.code == "draw_not_enough":
        return _("There are not enough usable questions to draw for %(row)s.") % {
            "row": problem.detail
        }
    if problem.code == "draw_bank_missing":
        return _("The bank of the draw %(row)s no longer exists.") % {"row": problem.detail}
    if problem.code == "image_no_copy":
        return _(
            "Question %(number)s: an image has no copy, and this quiz shows copies. "
            "Save the question again, or change how images are shown."
        ) % {"number": problem.question_no}
    if problem.code == "draw_image_no_copy":
        return _(
            "The draw %(row)s holds an image with no copy, and this quiz shows copies. "
            "Save that question in the bank again, or change how images are shown."
        ) % {"row": problem.detail}
    if problem.code == "requirement":
        return str(problem.detail)
    if problem.code == "requirement_conflict":
        return _(
            "Question types of this quiz need settings that exclude each other: %(detail)s"
        ) % {"detail": problem.detail}
    if problem.code == "type_unavailable":
        return _("Question %(number)s: its question type is not available.") % {
            "number": problem.question_no
        }
    return _("Question %(number)s, language %(locale)s: %(detail)s") % {
        "number": problem.question_no,
        "locale": problem.locale,
        "detail": problem.detail,
    }


def _publication_problems(quiz: Quiz) -> list[str]:
    problems = authoring.validate_for_publication(quiz)
    if not problems and not authoring.has_changes(quiz):
        problems = [authoring.Problem(None, None, "no_changes")]
    return [problem_text(problem) for problem in problems]


def _starting(request: HttpRequest, quiz: Quiz) -> bool:
    """`Start` publishes and opens a run; if a run appeared meanwhile, only publication is left."""
    wanted = "1" in (request.GET.get("start"), request.POST.get("start"))
    return wanted and quiz_state.of(quiz).open_run is None


def _publish_page(request: HttpRequest, quiz: Quiz, message: str | None = None) -> HttpResponse:
    new = authoring.future_snapshot(quiz)
    published = authoring.latest_published(quiz)
    context = {
        "quiz": quiz,
        "title": quiz_title(quiz),
        "problems": _publication_problems(quiz),
        "image_check": image_check(quiz),
        "message": message,
        "diff": revision_diff.compare(
            published.snapshot_json if published else None, new, revision_diff.locales_of(new)
        ),
        "outcome": authoring.round_outcome(quiz),
        "snapshot_hash": authoring.snapshot_hash(quiz),
        "starting": _starting(request, quiz),
    }
    return page(request, "admin/publish.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@not_archived
def quiz_publish(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method != "POST":
        return _publish_page(request, quiz)
    admin_id = str(request.user.pk)
    expected_hash = request.POST.get("snapshot_hash", "")
    try:
        if _starting(request, quiz):
            run = authoring.publish_and_open(quiz, admin_id=admin_id, expected_hash=expected_hash)
            return redirect("admin_run", run.id)
        authoring.publish(
            quiz,
            admin_id=admin_id,
            decision=request.POST.get("decision"),
            expected_hash=expected_hash,
        )
    except authoring.PublicationError:
        return _publish_page(request, quiz)
    except authoring.StalePublication:
        message = _("The quiz changed in the meantime. Check the changes and publish again.")
        return _publish_page(request, quiz, message)
    except authoring.RoundDecisionRequired:
        return _publish_page(request, quiz, _("Choose what happens to the running run."))
    except authoring.RunAlreadyOpen:
        return _publish_page(request, quiz, _("This quiz already has a running run."))
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
@require_POST
def run_open(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        run = authoring.open_run(quiz, admin_id=str(request.user.pk))
    except authoring.NothingPublished:
        return edit_page(request, quiz, run_error=_("Publish the quiz first."))
    except authoring.RunAlreadyOpen:
        return edit_page(request, quiz, run_error=_("This quiz already has a running run."))
    except authoring.RequirementUnmet as error:
        return edit_page(request, quiz, run_error=" ".join(error.reasons))
    return redirect("admin_run", run.id)


@admin_required
def quiz_duplicate(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    form = DuplicateQuizForm(request.POST or None, initial={"slug": _free_slug(quiz)})
    if request.method == "POST" and form.is_valid():
        slug = form.cleaned_data["slug"]
        try:
            copied = authoring.duplicate_quiz(quiz, slug, admin_id=str(request.user.pk))
        except authoring.SlugTaken:  # another admin took it at the same moment
            form.add_error("slug", _("Another quiz already uses this identifier."))
        else:
            return redirect("admin_quiz_edit", copied.id)
    context = {"quiz": quiz, "title": quiz_title(quiz), "form": form}
    return page(request, "admin/quiz_duplicate.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_POST
def quiz_archive(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        authoring.archive_quiz(quiz, admin_id=str(request.user.pk))
    except authoring.RunStillOpen:
        message = _("A run is in progress. End it before archiving the quiz.")
        return settings_page(request, quiz, run_error=message, status=409)
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@require_POST
def quiz_restore(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    authoring.restore_quiz(quiz, admin_id=str(request.user.pk))
    return redirect("admin_quiz_edit", quiz.id)
