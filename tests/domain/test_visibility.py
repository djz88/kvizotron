"""Who sees a stored answer and a photo (AC-57, AC-58)."""

import pytest

from app.domain import authoring, grading, settings, visibility
from app.domain.models import Attempt, AttemptAnswer, QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz
from tests.support.graded import add_graded

pytestmark = pytest.mark.django_db


@pytest.fixture
def quiz(graded_type):
    quiz = make_quiz()
    add_graded(quiz)
    return quiz


def row_of(quiz, *, closed=False, approved=False, kind=QuizRun.Kind.NORMAL, asset="a" * 32):
    from app.domain import attempts, run_links

    authoring.publish(quiz, admin_id=ADMIN_ID)
    revision = authoring.latest_published(quiz)
    if kind == QuizRun.Kind.TEST:
        run = run_links.create(quiz, revision, expires_at=None, admin_id=ADMIN_ID).run
    else:
        run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    started = attempts.start(run)
    question = attempts.questions_of(started.attempt)[0]
    attempts.submit(
        started.attempt.id, started.token, {question["id"]: {"image": asset}}, "key-00000001"
    )
    row = AttemptAnswer.objects.get()
    if approved:
        grading.set_approved(row, True, admin_id=ADMIN_ID)
    if closed:
        authoring.close_run(run, admin_id=ADMIN_ID)
    row = AttemptAnswer.objects.select_related("attempt__run").get()
    return row, question


def set_level(quiz, level):
    settings.set_override("photo_visibility", quiz, level, admin_id=ADMIN_ID)


@pytest.fixture
def photo_setting():
    """The real type's module is installed, so its setting exists."""
    assert "photo_visibility" in settings.CATALOGUE


def test_default_level_is_author(quiz, photo_setting):
    assert visibility.photo_level(quiz, None) == "author"


@pytest.mark.parametrize(
    "level,author,public",
    [("admins", False, False), ("author", True, False), ("public", True, True)],
)
def test_levels_decide(quiz, photo_setting, level, author, public):
    set_level(quiz, level)
    row, question = row_of(quiz, closed=True, approved=True)
    assert visibility.author_sees_photo(row, quiz, question) is author
    assert visibility.public_sees_photo(row, quiz, question) is public


def test_public_needs_approval(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz, closed=True)
    assert visibility.public_sees_photo(row, quiz, question) is False


def test_public_needs_the_run_to_have_ended(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz, approved=True)
    assert visibility.public_sees_photo(row, quiz, question) is False


def test_public_never_from_a_test_run(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz, approved=True, kind=QuizRun.Kind.TEST)
    QuizRun.all_kinds.filter(pk=row.attempt.run_id).update(status=QuizRun.Status.CLOSED)
    row = AttemptAnswer.objects.select_related("attempt__run").get()
    assert visibility.public_sees_photo(row, quiz, question) is False


def test_removed_is_seen_by_nobody(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz, closed=True, approved=True)
    grading.remove_photo(row, admin_id=ADMIN_ID)
    assert visibility.author_sees_photo(row, quiz, question) is False
    assert visibility.public_sees_photo(row, quiz, question) is False


def test_question_override_wins(quiz, photo_setting):
    set_level(quiz, "admins")
    row, question = row_of(quiz)
    shown = {**question, "settings": {**question["settings"], "photo_visibility": "author"}}
    assert visibility.author_sees_photo(row, quiz, shown) is True


def test_participant_sees_answers_only_when_allowed(quiz, photo_setting):
    row, _question = row_of(quiz)
    assert visibility.participant_sees_answers(row.attempt) is False
    settings.set_override(settings.STORE_ANSWERS, quiz, "all", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "participant", admin_id=ADMIN_ID)
    assert visibility.participant_sees_answers(row.attempt) is True


def test_has_more_to_see(quiz, photo_setting):
    set_level(quiz, "admins")
    row, _question = row_of(quiz)
    assert visibility.has_more_to_see(row.attempt) is False
    set_level(quiz, "author")
    assert visibility.has_more_to_see(row.attempt) is True


def test_plain_attempt_has_nothing_more(photo_setting):
    from app.domain import attempts

    quiz = make_quiz()
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    started = attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    assert visibility.has_more_to_see(started.attempt) is False


def test_public_needs_the_notice_at_the_start_of_the_attempt(quiz, photo_setting):
    """Raised after the attempt began: the participant was never told, so the photo stays."""
    set_level(quiz, "author")
    row, question = row_of(quiz, closed=True)
    set_level(quiz, "public")
    grading.set_approved(row, True, admin_id=ADMIN_ID)
    row = AttemptAnswer.objects.select_related("attempt__run").get()
    assert visibility.may_be_approved(row, quiz, question) is False
    assert visibility.public_sees_photo(row, quiz, question) is False


def test_public_from_the_start_can_be_approved(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz)
    assert visibility.may_be_approved(row, quiz, question) is True


def test_attempt_older_than_the_notice_is_never_public(quiz, photo_setting):
    set_level(quiz, "public")
    row, question = row_of(quiz, closed=True, approved=True)
    Attempt.objects.filter(pk=row.attempt_id).update(settings_json={})
    row = AttemptAnswer.objects.select_related("attempt__run").get()
    assert visibility.public_sees_photo(row, quiz, question) is False
