import json
from unittest import mock

import pytest

from app.domain import authoring
from app.domain.models import QuizRevision, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_B,
    add_question,
    make_quiz,
    open_quiz_run,
    published_quiz,
)

pytestmark = pytest.mark.django_db


def problems_of(error):
    return {(p.question_no, p.locale, p.code) for p in error.value.problems}


def publish(quiz):
    return authoring.publish(quiz, admin_id=ADMIN_ID)


def test_publish_builds_snapshot_with_plugin_versions_and_checksum():
    quiz = make_quiz(locales=("cs", "en"))
    question_id = add_question(quiz)
    revision = publish(quiz)
    assert revision.status == QuizRevision.Status.PUBLISHED
    assert revision.published_at is not None
    assert revision.revision_no == 1
    question = revision.snapshot_json["questions"][0]
    assert question["id"] == question_id
    assert question["type"] == "choice.single"
    assert question["type_version"] == "1.0.0"
    assert question["scoring"] == "all_or_nothing"
    assert question["scoring_version"] == "1.0.0"
    assert question["settings"] == {"points": 1}
    assert revision.plugins_json == {
        "question_types": {"choice.single": "1.0.0"},
        "scoring": {"all_or_nothing": "1.0.0"},
    }
    assert len(revision.checksum) == 64


def test_published_snapshot_keeps_title_and_locales_after_quiz_edit():
    quiz = published_quiz(locales=("cs", "en"))
    revision = quiz.revisions.get()
    quiz.title = {"cs": "Jiný"}
    quiz.supported_locales = ["cs"]
    quiz.save()
    revision.refresh_from_db()
    assert revision.snapshot_json["title"] == {"cs": "Název cs", "en": "Název en"}
    assert revision.snapshot_json["locales"] == ["cs", "en"]
    assert revision.snapshot_json["default_locale"] == "cs"


def test_publish_without_questions_is_refused():
    with pytest.raises(authoring.PublicationError) as error:
        publish(make_quiz())
    assert problems_of(error) == {(None, None, "no_questions")}


def test_publish_with_missing_title_in_required_locale_is_refused():
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    quiz.title = {"cs": "Název", "uk": " "}
    quiz.save()
    with pytest.raises(authoring.PublicationError) as error:
        publish(quiz)
    assert problems_of(error) == {(None, "uk", "title_missing")}


def test_publish_with_incomplete_translation_names_question_and_locale():
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    second = add_question(quiz)
    config = {
        "prompt": {"cs": "Otázka", "uk": ""},
        "options": [
            {"id": "a", "text": {"cs": "A", "uk": "А"}},
            {"id": "b", "text": {"cs": "B", "uk": "Б"}},
        ],
        "correct": "a",
    }
    authoring.save_question(quiz, second, "choice.single", config)
    with pytest.raises(authoring.PublicationError) as error:
        publish(quiz)
    assert problems_of(error) == {(2, "uk", "invalid")}
    assert error.value.problems[0].detail
    assert not QuizRevision.objects.filter(status="PUBLISHED").exists()


def test_cs_uk_quiz_publishes_without_english():
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    assert publish(quiz).snapshot_json["locales"] == ["cs", "uk"]


def test_publish_supersedes_previous_revision():
    quiz = published_quiz()
    add_question(quiz)
    second = publish(quiz)
    assert second.revision_no == 2
    assert list(quiz.revisions.order_by("revision_no").values_list("status", flat=True)) == [
        "SUPERSEDED",
        "PUBLISHED",
    ]


def test_publishing_again_without_changes_is_refused():
    quiz = published_quiz()
    with pytest.raises(authoring.PublicationError) as error:
        publish(quiz)
    assert problems_of(error) == {(None, None, "no_changes")}


def test_editing_after_publication_creates_draft_and_leaves_published_untouched():
    quiz = published_quiz()
    published = quiz.revisions.get(status="PUBLISHED")
    frozen = json.dumps(published.snapshot_json, sort_keys=True)
    question_id = published.snapshot_json["questions"][0]["id"]
    add_question(quiz, OPTION_B, "Změněno", question_id)
    draft = authoring.get_draft(quiz)
    assert draft.status == QuizRevision.Status.DRAFT
    assert draft.revision_no == 2
    assert draft.snapshot_json["questions"][0]["definition"]["correct"] == OPTION_B
    published.refresh_from_db()
    assert json.dumps(published.snapshot_json, sort_keys=True) == frozen


def test_editable_questions_come_from_draft_or_latest_published():
    quiz = make_quiz()
    assert authoring.editable_questions(quiz) == []
    first = add_question(quiz)
    publish(quiz)
    assert [q["id"] for q in authoring.editable_questions(quiz)] == [first]
    assert not quiz.revisions.filter(status="DRAFT").exists()


def test_delete_question_removes_it_from_draft_only():
    quiz = published_quiz(questions=2)
    published = quiz.revisions.get(status="PUBLISHED")
    removed = published.snapshot_json["questions"][0]["id"]
    authoring.delete_question(quiz, removed)
    assert removed not in [q["id"] for q in authoring.editable_questions(quiz)]
    published.refresh_from_db()
    assert len(published.snapshot_json["questions"]) == 2


def test_edit_or_delete_of_unknown_question_is_refused():
    quiz = make_quiz()
    with pytest.raises(authoring.QuestionNotFound):
        add_question(quiz, question_id="nope")
    with pytest.raises(authoring.QuestionNotFound):
        authoring.delete_question(quiz, "nope")


def test_unknown_question_type_is_refused():
    with pytest.raises(authoring.UnknownQuestionType):
        authoring.save_question(make_quiz(), None, "no.such", {})


def test_max_score_is_sum_of_question_max_scores():
    assert published_quiz(questions=3).revisions.get().max_score == 3


def test_publish_is_audited_and_emits_quiz_published():
    quiz = make_quiz()
    add_question(quiz)
    with mock.patch("app.domain.authoring.events.emit") as emit:
        revision = publish(quiz)
    event = AuditEvent.objects.get(action="quiz.published")
    assert event.actor_id == ADMIN_ID
    assert event.entity_id == str(quiz.id)
    assert "correct" not in json.dumps(event.details_json)
    emit.assert_called_once_with(
        "quiz.published", {"quiz_id": str(quiz.id), "revision_id": str(revision.id)}
    )


def test_open_run_needs_published_revision():
    with pytest.raises(authoring.NothingPublished):
        authoring.open_run(make_quiz(), admin_id=ADMIN_ID)


def test_open_run_uses_latest_published_and_numbers_runs():
    quiz = published_quiz()
    first = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert (first.run_no, first.status) == (1, QuizRun.Status.OPEN)
    authoring.close_run(first, admin_id=ADMIN_ID)
    add_question(quiz)
    newest = publish(quiz)
    second = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert (second.run_no, second.current_revision_id) == (2, newest.id)


def test_draft_does_not_reach_a_new_run():
    quiz = published_quiz()
    published = quiz.revisions.get(status="PUBLISHED")
    add_question(quiz)
    assert authoring.open_run(quiz, admin_id=ADMIN_ID).current_revision_id == published.id


def test_second_open_run_raises_run_already_open():
    run = open_quiz_run()
    with pytest.raises(authoring.RunAlreadyOpen):
        authoring.open_run(run.quiz, admin_id=ADMIN_ID)


def test_close_run_is_audited_and_emits_run_closed():
    run = open_quiz_run()
    with mock.patch("app.domain.authoring.events.emit") as emit:
        authoring.close_run(run, admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.CLOSED
    assert run.closed_at is not None
    assert AuditEvent.objects.filter(action="run.closed", entity_id=str(run.id)).exists()
    emit.assert_called_once_with("run.closed", {"run_id": str(run.id)})


def test_closing_a_closed_run_changes_nothing():
    run = open_quiz_run()
    authoring.close_run(run, admin_id=ADMIN_ID)
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert AuditEvent.objects.filter(action="run.closed").count() == 1
