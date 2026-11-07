"""Starting a quiz publishes it and opens a run together, or does neither."""

from unittest.mock import patch

import pytest

from app.domain import authoring
from app.domain.models import QuizRevision, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz

pytestmark = pytest.mark.django_db


def ready():
    quiz = make_quiz()
    add_question(quiz)
    return quiz


def test_publish_and_open_does_both():
    quiz = ready()
    run = authoring.publish_and_open(quiz, admin_id=ADMIN_ID)
    revision = authoring.latest_published(quiz)
    assert run.current_revision == revision and run.status == QuizRun.Status.OPEN
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"quiz.published", "run.opened"} <= actions


def test_failure_to_open_keeps_the_draft_unpublished():
    quiz = ready()
    with (
        patch.object(authoring, "open_run", side_effect=authoring.RunAlreadyOpen("x")),
        pytest.raises(authoring.RunAlreadyOpen),
    ):
        authoring.publish_and_open(quiz, admin_id=ADMIN_ID)
    assert authoring.latest_published(quiz) is None
    assert quiz.revisions.get().status == QuizRevision.Status.DRAFT
    assert not AuditEvent.objects.filter(action="quiz.published").exists()


def test_stale_hash_changes_nothing():
    quiz = ready()
    with pytest.raises(authoring.StalePublication):
        authoring.publish_and_open(quiz, admin_id=ADMIN_ID, expected_hash="old")
    assert authoring.latest_published(quiz) is None
    assert not quiz.runs.exists()


def test_quiz_with_problems_publishes_nothing():
    quiz = make_quiz()
    with pytest.raises(authoring.PublicationError):
        authoring.publish_and_open(quiz, admin_id=ADMIN_ID)
    assert not quiz.runs.exists()
