"""Which action the main button of a quiz offers, in every state (FR-51)."""

import pytest

from app.domain import authoring, quiz_state
from app.domain.quiz_state import MainAction, SecondaryAction
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz

pytestmark = pytest.mark.django_db


def change(quiz):
    add_question(quiz, prompt="Další")
    return quiz


def never_published_draft():
    return change(make_quiz())


def published_never_started():
    return published_quiz()


def never_started_with_changes():
    return change(published_quiz())


def finished():
    quiz = published_quiz()
    authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    return quiz


def finished_with_changes():
    return change(finished())


def running_no_changes():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    return quiz


def running_with_changes():
    return change(running_no_changes())


def archived():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    return quiz


PUBLISH_DISCARD = (SecondaryAction.PUBLISH_ONLY, SecondaryAction.DISCARD)


@pytest.mark.parametrize(
    ("setup", "main", "secondary"),
    [
        (never_published_draft, MainAction.START, (SecondaryAction.PUBLISH_ONLY,)),
        (published_never_started, MainAction.START, ()),
        (never_started_with_changes, MainAction.START, PUBLISH_DISCARD),
        (finished, MainAction.START_AGAIN, ()),
        (finished_with_changes, MainAction.START_AGAIN, PUBLISH_DISCARD),
        (
            running_with_changes,
            MainAction.PUBLISH_CHANGES,
            (SecondaryAction.DISCARD, SecondaryAction.END_RUN),
        ),
        (running_no_changes, MainAction.END_RUN, ()),
        (archived, MainAction.RESTORE, (SecondaryAction.DUPLICATE,)),
    ],
    ids=lambda value: getattr(value, "__name__", None),
)
def test_main_action_follows_the_quiz_state(setup, main, secondary):
    state = quiz_state.of(setup())
    assert state.main == main
    assert state.secondary == secondary


def test_empty_new_quiz_starts_through_the_publication_page():
    state = quiz_state.of(make_quiz())
    assert state.main == MainAction.START
    assert state.secondary == ()
    assert state.needs_publication_page


def test_published_quiz_without_changes_starts_directly():
    assert not quiz_state.of(published_never_started()).needs_publication_page


def test_quiz_with_changes_starts_through_the_publication_page():
    assert quiz_state.of(never_started_with_changes()).needs_publication_page


def test_state_names_the_finished_run():
    state = quiz_state.of(finished())
    assert state.open_run is None and state.last_run.run_no == 1


def test_state_names_the_open_run():
    assert quiz_state.of(running_no_changes()).open_run.run_no == 1


def test_new_quiz_has_no_published_revision():
    assert quiz_state.of(make_quiz()).published_no is None


def test_state_names_the_published_revision():
    assert quiz_state.of(published_never_started()).published_no == 1


def test_state_says_when_a_quiz_is_archived():
    assert quiz_state.of(archived()).archived
