"""History of a quiz, comparing revisions, returning to one and discarding a draft (FR-08)."""

from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.api.admin_auth import admin_required
from app.api.admin_common import confirm_page
from app.api.admin_quizzes import edit_page, not_archived
from app.api.admin_workspace import workspace
from app.api.rendering import page
from app.domain import authoring, revision_diff, selection
from app.domain.models import Quiz, QuizRevision

STATUS_LABELS = {
    QuizRevision.Status.DRAFT: gettext_lazy("Draft"),
    QuizRevision.Status.PUBLISHED: gettext_lazy("Published"),
    QuizRevision.Status.SUPERSEDED: gettext_lazy("Superseded"),
    QuizRevision.Status.ARCHIVED: gettext_lazy("Archived"),
}


def _revision(quiz: Quiz, revision_no: int) -> QuizRevision:
    """Drafts have their own page, and their snapshot is not yet complete."""
    revision = quiz.revisions.filter(revision_no=revision_no).first()
    if revision is None or revision.status == QuizRevision.Status.DRAFT:
        raise Http404
    return revision


@admin_required
def revisions(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    rows = [
        {
            "no": revision.revision_no,
            "status": STATUS_LABELS[QuizRevision.Status(revision.status)],
            "published_at": revision.published_at,
            "questions": selection.count(revision.snapshot_json),
            "max_score": revision.max_score,
            "is_draft": revision.status == QuizRevision.Status.DRAFT,
        }
        for revision in quiz.revisions.order_by("-revision_no")
    ]
    context = workspace(quiz, "revisions") | {"rows": rows}
    return page(request, "admin/revisions.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
def compare(request: HttpRequest, quiz_id: UUID, revision_no: int) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    revision = _revision(quiz, revision_no)
    previous = (
        quiz.revisions.filter(revision_no__lt=revision_no)
        .exclude(status=QuizRevision.Status.DRAFT)
        .order_by("-revision_no")
        .first()
    )
    new = revision.snapshot_json
    context = {
        "quiz": quiz,
        "revision": revision,
        "previous": previous,
        "diff": revision_diff.compare(
            previous.snapshot_json if previous else None, new, revision_diff.locales_of(new)
        ),
    }
    return page(request, "admin/revision_compare.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@not_archived
def restore(request: HttpRequest, quiz_id: UUID, revision_no: int) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    revision = _revision(quiz, revision_no)
    confirmed = "confirm" in request.POST or not authoring.has_draft(quiz)
    if request.method != "POST" or not confirmed:
        return _confirm(
            request,
            quiz,
            _("Use revision %(no)s as a new draft? Unpublished changes will be replaced.")
            % {"no": revision_no},
            reverse("admin_revision_restore", args=[quiz.id, revision_no]),
        )
    authoring.use_as_draft(quiz, revision, admin_id=str(request.user.pk))
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
def discard(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if not authoring.has_draft(quiz):
        return edit_page(request, quiz, run_error=_("There are no unpublished changes."))
    if authoring.latest_published(quiz) is None:
        message = _("This quiz was never published, so there is nothing to return to.")
        return edit_page(request, quiz, run_error=message)
    if request.method != "POST":
        return _confirm(
            request,
            quiz,
            _("Discard all unpublished changes? This cannot be undone."),
            reverse("admin_draft_discard", args=[quiz.id]),
        )
    authoring.discard_draft(quiz, admin_id=str(request.user.pk))
    return redirect("admin_quiz_edit", quiz.id)


def _confirm(request: HttpRequest, quiz: Quiz, message: str, action: str) -> HttpResponse:
    return confirm_page(request, quiz=quiz, message=message, action=action)
