"""Where a quiz stands, and so which action its main button offers (FR-51).

The labels are in the UI; here is only the rule, so that it can be tested without HTML.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain import authoring
from app.domain.models import Quiz, QuizRun


class MainAction(StrEnum):
    START = "start"
    START_AGAIN = "start_again"
    PUBLISH_CHANGES = "publish_changes"
    END_RUN = "end_run"
    RESTORE = "restore"


class SecondaryAction(StrEnum):
    PUBLISH_ONLY = "publish_only"
    DISCARD = "discard"
    END_RUN = "end_run"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class QuizState:
    main: MainAction
    secondary: tuple[SecondaryAction, ...]
    has_changes: bool
    published_no: int | None
    open_run: QuizRun | None
    last_run: QuizRun | None
    archived: bool
    needs_publication_page: bool


def _actions(
    quiz: Quiz,
    has_changes: bool,
    can_discard: bool,
    open_run: QuizRun | None,
    last_run: QuizRun | None,
) -> tuple[MainAction, tuple[SecondaryAction, ...]]:
    discard = (SecondaryAction.DISCARD,) if can_discard else ()
    if quiz.archived_at is not None:
        return MainAction.RESTORE, (SecondaryAction.DUPLICATE,)
    if open_run is not None and has_changes:
        return MainAction.PUBLISH_CHANGES, (*discard, SecondaryAction.END_RUN)
    if open_run is not None:
        return MainAction.END_RUN, ()
    main = MainAction.START if last_run is None else MainAction.START_AGAIN
    return main, ((SecondaryAction.PUBLISH_ONLY, *discard) if has_changes else ())


def of(quiz: Quiz) -> QuizState:
    has_changes = authoring.has_changes(quiz)
    published = authoring.latest_published(quiz)
    published_no = published.revision_no if published else None
    open_run = quiz.runs.filter(status=QuizRun.Status.OPEN).first()
    last_run = quiz.runs.order_by("-run_no").first()
    can_discard = authoring.has_draft(quiz) and published_no is not None
    main, secondary = _actions(quiz, has_changes, can_discard, open_run, last_run)
    return QuizState(
        main=main,
        secondary=secondary,
        has_changes=has_changes,
        published_no=published_no,
        open_run=open_run,
        last_run=last_run,
        archived=quiz.archived_at is not None,
        needs_publication_page=has_changes or published_no is None,
    )
