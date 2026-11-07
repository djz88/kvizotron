"""A quiz has a short translated description (FR-52), handled like its title."""

import pytest

from app.domain import authoring, revision_diff
from app.domain.models import QuizRevision
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz

pytestmark = pytest.mark.django_db


def test_missing_description_blocks_publication():
    quiz = make_quiz(description={})
    add_question(quiz)
    assert authoring.Problem(None, "cs", "description_missing") in (
        authoring.validate_for_publication(quiz)
    )


def test_each_selected_language_needs_a_description():
    quiz = make_quiz(locales=("cs", "en"), description={"cs": "x"})
    add_question(quiz)
    found = [
        problem
        for problem in authoring.validate_for_publication(quiz)
        if problem.code == "description_missing"
    ]
    assert [problem.locale for problem in found] == ["en"]


def test_blank_description_counts_as_missing():
    quiz = make_quiz(description={"cs": "   "})
    add_question(quiz)
    codes = [problem.code for problem in authoring.validate_for_publication(quiz)]
    assert "description_missing" in codes


def test_description_is_frozen_in_the_snapshot():
    quiz = published_quiz(description={"cs": "x"})
    revision = authoring.latest_published(quiz)
    assert revision.snapshot_json["description"] == {"cs": "x"}
    before = authoring.snapshot_hash(quiz)
    quiz.description = {"cs": "y"}
    assert authoring.snapshot_hash(quiz) != before


def test_discard_restores_the_description():
    quiz = published_quiz(description={"cs": "a"})
    quiz.description = {"cs": "b"}
    quiz.save()
    authoring.get_draft(quiz)
    authoring.discard_draft(quiz, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.description == {"cs": "a"}


def test_return_to_a_revision_restores_its_description():
    quiz = published_quiz(description={"cs": "a"})
    first = authoring.latest_published(quiz)
    quiz.description = {"cs": "b"}
    quiz.save()
    authoring.get_draft(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.use_as_draft(quiz, first, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.description == {"cs": "a"}


def test_duplicate_copies_the_description():
    quiz = published_quiz(description={"cs": "a"})
    copy = authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    assert copy.description == {"cs": "a"}


def old_revision(quiz):
    """Revisions published before descriptions existed have no such key in the snapshot."""
    revision = authoring.latest_published(quiz)
    snapshot = dict(revision.snapshot_json)
    del snapshot["description"]
    QuizRevision.objects.filter(pk=revision.pk).update(snapshot_json=snapshot)
    return QuizRevision.objects.get(pk=revision.pk)


def test_old_snapshot_without_description_can_be_restored():
    quiz = published_quiz()
    revision = old_revision(quiz)
    authoring.use_as_draft(quiz, revision, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.description == {}


def test_old_snapshot_without_description_can_be_compared():
    quiz = published_quiz(description={"cs": "nový"})
    revision = old_revision(quiz)
    new = authoring.future_snapshot(quiz)
    diff = revision_diff.compare(revision.snapshot_json, new, revision_diff.locales_of(new))
    assert [(field.locale, field.before, field.after) for field in diff.quiz_fields] == [
        ("cs", None, "nový")
    ]
