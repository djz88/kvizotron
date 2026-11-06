import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from app.domain.models import Attempt, ImmutableRevision, Quiz, QuizRevision, QuizRun
from tests.domain.helpers import make_quiz, open_quiz_run, published_quiz

pytestmark = pytest.mark.django_db


def test_slug_is_unique():
    make_quiz("kviz")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_quiz("kviz")


def test_revision_number_is_unique_per_quiz():
    quiz = make_quiz()
    QuizRevision.objects.create(quiz=quiz, revision_no=1, status="SUPERSEDED", snapshot_json={})
    with pytest.raises(IntegrityError), transaction.atomic():
        QuizRevision.objects.create(quiz=quiz, revision_no=1, status="SUPERSEDED", snapshot_json={})


def test_published_revision_cannot_be_saved():
    revision = published_quiz().revisions.get()
    original = revision.snapshot_json
    revision.snapshot_json = {"questions": []}
    with pytest.raises(ImmutableRevision):
        revision.save()
    assert QuizRevision.objects.get(pk=revision.pk).snapshot_json == original


def test_draft_revision_can_be_saved():
    revision = QuizRevision.objects.create(
        quiz=make_quiz(), revision_no=1, snapshot_json={"questions": []}
    )
    revision.snapshot_json = {"questions": [{}]}
    revision.save()
    assert QuizRevision.objects.get(pk=revision.pk).snapshot_json == {"questions": [{}]}
    assert revision.status == QuizRevision.Status.DRAFT


def test_second_draft_for_a_quiz_is_refused_by_the_database():
    quiz = make_quiz()
    QuizRevision.objects.create(quiz=quiz, revision_no=1, snapshot_json={})
    with pytest.raises(IntegrityError), transaction.atomic():
        QuizRevision.objects.create(quiz=quiz, revision_no=2, snapshot_json={})


def test_second_open_run_for_a_quiz_is_refused_by_the_database():
    run = open_quiz_run()
    with pytest.raises(IntegrityError), transaction.atomic():
        QuizRun.objects.create(quiz=run.quiz, run_no=2, current_revision=run.current_revision)


def test_ids_are_uuid7():
    run = open_quiz_run()
    attempt = Attempt.objects.create(run=run, revision=run.current_revision)
    for entity in (run.quiz, run.current_revision, run, attempt):
        assert entity.pk.version == 7


def test_revision_with_attempts_cannot_be_deleted():
    run = open_quiz_run()
    Attempt.objects.create(run=run, revision=run.current_revision)
    with pytest.raises(ProtectedError):
        run.delete()
    with pytest.raises(ProtectedError):
        run.current_revision.delete()


def test_new_quiz_is_not_featured():
    assert Quiz.objects.get(pk=make_quiz().pk).featured is False
