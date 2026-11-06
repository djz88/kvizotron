"""Quiz list and editor. Rules live in app.domain.authoring and in question type plugins."""

from typing import Any, cast
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from markupsafe import Markup

from app.api.admin_auth import admin_required
from app.api.admin_forms import QuizForm
from app.api.rendering import page
from app.contracts import AdminFormError, QuestionTypePlugin
from app.domain import authoring
from app.domain.models import Quiz, QuizRevision, QuizRun
from app.kernel import registry


def _title(quiz: Quiz) -> str:
    return quiz.title.get(quiz.default_locale) or quiz.slug


def _published_no(quiz: Quiz) -> int | None:
    revision = quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).first()
    return revision.revision_no if revision else None


@admin_required
def quiz_list(request: HttpRequest) -> HttpResponse:
    quizzes = [
        {
            "id": quiz.id,
            "title": _title(quiz),
            "slug": quiz.slug,
            "published_no": _published_no(quiz),
            "has_draft": quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists(),
            "open_run": quiz.runs.filter(status=QuizRun.Status.OPEN).first(),
        }
        for quiz in Quiz.objects.order_by("-created_at")
    ]
    return page(request, "admin/quiz_list.html", {"quizzes": quizzes}, request.locale)  # type: ignore[attr-defined]


@admin_required
def quiz_new(request: HttpRequest) -> HttpResponse:
    form = QuizForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        quiz = form.apply_to(Quiz())
        return redirect("admin_quiz_edit", quiz.id)
    return page(request, "admin/quiz_form.html", {"form": form}, request.locale)  # type: ignore[attr-defined]


def _question_label(question: dict[str, Any], locale: str) -> str:
    """Plugins may not agree on a prompt field; the type id is the fallback."""
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
        payload = plugin.public_payload(question["definition"], locale)
    except LookupError, TypeError, ValueError, AttributeError:
        return question["type"]
    return payload.get("prompt") or question["type"]


def _edit_page(
    request: HttpRequest,
    quiz: Quiz,
    form: QuizForm | None = None,
    problems: list[str] | None = None,
    run_error: str | None = None,
) -> HttpResponse:
    questions = [
        {
            "id": question["id"],
            "number": number,
            "label": _question_label(question, quiz.default_locale),
        }
        for number, question in enumerate(authoring.editable_questions(quiz), start=1)
    ]
    context = {
        "quiz": quiz,
        "title": _title(quiz),
        "form": form or QuizForm(quiz=quiz),
        "questions": questions,
        "question_types": registry.keys("question_type"),
        "published_no": _published_no(quiz),
        "has_draft": quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists(),
        "open_run": quiz.runs.filter(status=QuizRun.Status.OPEN).first(),
        "problems": problems or [],
        "run_error": run_error,
        "public_url": request.build_absolute_uri(f"/q/{quiz.slug}"),
    }
    return page(request, "admin/quiz_edit.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def quiz_edit(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method != "POST":
        return _edit_page(request, quiz)
    form = QuizForm(request.POST, quiz=quiz)
    if not form.is_valid():
        return _edit_page(request, quiz, form=form)
    form.apply_to(quiz)
    if form.has_changed():
        authoring.get_draft(quiz)  # so that the change can be published
    return redirect("admin_quiz_edit", quiz.id)


def _enabled_plugin(type_id: str) -> QuestionTypePlugin:
    if type_id not in registry.keys("question_type"):
        raise Http404
    return cast(QuestionTypePlugin, registry.get("question_type", type_id))


def _question_page(
    request: HttpRequest,
    quiz: Quiz,
    plugin: QuestionTypePlugin,
    config: Any,
    error: str | None = None,
) -> HttpResponse:
    context = {
        "quiz": quiz,
        "type_id": plugin.id,
        "editor": Markup(plugin.render_admin(config, quiz.supported_locales)),  # noqa: S704  # the plugin escapes through its own template
        "error": error,
    }
    return page(request, "admin/question_form.html", context, request.locale)  # type: ignore[attr-defined]


def _save_question(
    request: HttpRequest,
    quiz: Quiz,
    plugin: QuestionTypePlugin,
    question_id: str | None,
    current: Any,
) -> HttpResponse:
    try:
        config = plugin.parse_admin(dict(request.POST.lists()), quiz.supported_locales)
    except AdminFormError as error:
        return _question_page(request, quiz, plugin, error.config, str(error))
    except ValueError as error:
        return _question_page(request, quiz, plugin, current, str(error))
    authoring.save_question(quiz, question_id, plugin.id, config)
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
def question_new(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    plugin = _enabled_plugin(request.GET.get("type", ""))
    if request.method == "POST":
        return _save_question(request, quiz, plugin, None, {})
    return _question_page(request, quiz, plugin, {})


def _existing_question(quiz: Quiz, question_id: str) -> dict[str, Any]:
    for question in authoring.editable_questions(quiz):
        if question["id"] == question_id:
            return question
    raise Http404


@admin_required
def question_edit(request: HttpRequest, quiz_id: UUID, question_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    question = _existing_question(quiz, question_id)
    plugin = _enabled_plugin(question["type"])
    if request.method == "POST":
        return _save_question(request, quiz, plugin, question_id, question["definition"])
    return _question_page(request, quiz, plugin, question["definition"])


@admin_required
@require_POST
def question_delete(request: HttpRequest, quiz_id: UUID, question_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    _existing_question(quiz, question_id)
    authoring.delete_question(quiz, question_id)
    return redirect("admin_quiz_edit", quiz.id)


def _problem_text(problem: authoring.Problem) -> str:
    if problem.code == "no_questions":
        return _("The quiz has no questions.")
    if problem.code == "no_changes":
        return _("There is nothing new to publish.")
    if problem.code == "title_missing":
        return _("The title is missing in language %(locale)s.") % {"locale": problem.locale}
    if problem.code == "type_unavailable":
        return _("Question %(number)s: its question type is not available.") % {
            "number": problem.question_no
        }
    return _("Question %(number)s, language %(locale)s: %(detail)s") % {
        "number": problem.question_no,
        "locale": problem.locale,
        "detail": problem.detail,
    }


@admin_required
@require_POST
def quiz_publish(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        authoring.publish(quiz, admin_id=str(request.user.pk))
    except authoring.PublicationError as error:
        return _edit_page(request, quiz, problems=[_problem_text(p) for p in error.problems])
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@require_POST
def run_open(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    try:
        run = authoring.open_run(quiz, admin_id=str(request.user.pk))
    except authoring.NothingPublished:
        return _edit_page(request, quiz, run_error=_("Publish the quiz first."))
    except authoring.RunAlreadyOpen:
        return _edit_page(request, quiz, run_error=_("This quiz already has an open round."))
    return redirect("admin_run", run.id)
