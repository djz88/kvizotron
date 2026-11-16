import json
from unittest import mock

import pytest

from app.contracts import EXTERNAL_IMAGE_MODE
from app.domain import authoring, questions, settings
from app.domain.models import AppSetting, BrandingConfiguration, Quiz, QuizRevision, QuizRun
from app.kernel.models import AuditEvent
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_B,
    add_question,
    definition,
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
    assert question["type"] == "choice"
    assert question["type_version"] == "1.0.0"
    assert question["scoring"] == "all_or_nothing"
    assert question["scoring_version"] == "1.0.0"
    assert question["settings"] == {"points": 1}
    assert revision.plugins_json == {
        "question_types": {"choice": "1.0.0"},
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
    """AC-03: an enabled language must be complete in every question before publication."""
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    second = add_question(quiz)
    config = {
        "prompt": {"cs": "Otázka", "uk": ""},
        "options": [
            {"id": "a", "text": {"cs": "A", "uk": "А"}},
            {"id": "b", "text": {"cs": "B", "uk": "Б"}},
        ],
        "correct": ["a"],
    }
    authoring.save_question(quiz, second, "choice", config)
    with pytest.raises(authoring.PublicationError) as error:
        publish(quiz)
    assert problems_of(error) == {(2, "uk", "invalid")}
    assert error.value.problems[0].detail
    assert not QuizRevision.objects.filter(status="PUBLISHED").exists()


def test_cs_uk_quiz_publishes_without_english():
    """AC-03: English is not required while it is not enabled for the quiz."""
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    assert publish(quiz).snapshot_json["locales"] == ["cs", "uk"]


def test_enabling_english_makes_it_required_for_publication():
    """AC-03: the same cs+uk quiz is refused once English is enabled without its texts."""
    quiz = make_quiz(locales=("cs", "uk"))
    add_question(quiz)
    quiz.supported_locales = ["cs", "uk", "en"]
    quiz.save()
    with pytest.raises(authoring.PublicationError) as error:
        publish(quiz)
    assert {(None, "en", "title_missing"), (1, "en", "invalid")} <= problems_of(error)
    assert not QuizRevision.objects.filter(status="PUBLISHED").exists()


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
    assert draft.snapshot_json["questions"][0]["definition"]["correct"] == [OPTION_B]
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


def test_stale_hash_is_refused_and_nothing_published():
    quiz = make_quiz()
    add_question(quiz)
    seen = authoring.snapshot_hash(quiz)
    add_question(quiz, prompt="Pozdější")
    with pytest.raises(authoring.StalePublication):
        authoring.publish(quiz, admin_id=ADMIN_ID, expected_hash=seen)
    assert not quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).exists()


def test_current_hash_publishes():
    quiz = make_quiz()
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID, expected_hash=authoring.snapshot_hash(quiz))
    assert quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).exists()


def test_title_change_changes_hash():
    quiz = make_quiz()
    add_question(quiz)
    before = authoring.snapshot_hash(quiz)
    quiz.title = {"cs": "Jiný"}
    assert authoring.snapshot_hash(quiz) != before


def test_question_change_changes_hash():
    quiz = make_quiz()
    question = add_question(quiz)
    before = authoring.snapshot_hash(quiz)
    add_question(quiz, prompt="Jiná", question_id=question)
    assert authoring.snapshot_hash(quiz) != before


def test_use_as_draft_copies_questions_and_quiz_fields():
    quiz = published_quiz(locales=("cs", "uk"))
    old = quiz.revisions.get()
    original_title = dict(quiz.title)
    quiz.title = {"cs": "Jiný"}
    quiz.supported_locales = ["cs"]
    quiz.save()
    add_question(quiz, prompt="Pozdější")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    draft = authoring.use_as_draft(quiz, old, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.title == original_title and quiz.supported_locales == ["cs", "uk"]
    assert [q["id"] for q in draft.snapshot_json["questions"]] == [
        q["id"] for q in old.snapshot_json["questions"]
    ]


def test_restore_keeps_an_archive_done_meanwhile():
    quiz = published_quiz()
    stale = Quiz.objects.get(pk=quiz.pk)
    authoring.archive_quiz(Quiz.objects.get(pk=quiz.pk), admin_id=ADMIN_ID)
    authoring._restore_quiz_fields(stale, quiz.revisions.first().snapshot_json)
    assert Quiz.objects.get(pk=quiz.pk).archived_at is not None


def test_use_as_draft_leaves_old_revision_identical():
    quiz = published_quiz()
    old = quiz.revisions.get()
    frozen = (old.checksum, old.snapshot_json, old.status)
    draft = authoring.use_as_draft(quiz, old, admin_id=ADMIN_ID)
    draft.snapshot_json["questions"].clear()
    draft.save()
    old.refresh_from_db()
    assert (old.checksum, old.snapshot_json, old.status) == frozen


def test_use_as_draft_publishes_under_a_new_number():
    quiz = published_quiz()
    add_question(quiz, prompt="Druhá")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    first = quiz.revisions.get(revision_no=1)
    authoring.use_as_draft(quiz, first, admin_id=ADMIN_ID)
    third = authoring.publish(quiz, admin_id=ADMIN_ID)
    assert third.revision_no == 3
    assert [q["id"] for q in third.snapshot_json["questions"]] == [
        q["id"] for q in first.snapshot_json["questions"]
    ]
    assert quiz.revisions.get(revision_no=1).status == QuizRevision.Status.SUPERSEDED


def test_use_as_draft_replaces_existing_draft():
    quiz = published_quiz()
    add_question(quiz, prompt="Rozepsaná")
    draft = authoring.use_as_draft(quiz, quiz.revisions.get(revision_no=1), admin_id=ADMIN_ID)
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).count() == 1
    assert len(draft.snapshot_json["questions"]) == 1


def test_discard_restores_fields_and_removes_draft():
    quiz = published_quiz()
    title = dict(quiz.title)
    quiz.title = {"cs": "Rozepsaný"}
    quiz.save()
    add_question(quiz, prompt="Rozepsaná")
    authoring.discard_draft(quiz, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.title == title
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()
    assert len(authoring.editable_questions(quiz)) == 1


def test_discard_never_published_is_refused():
    quiz = make_quiz()
    add_question(quiz)
    with pytest.raises(authoring.NeverPublished):
        authoring.discard_draft(quiz, admin_id=ADMIN_ID)
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_discard_without_draft_is_refused():
    with pytest.raises(authoring.NothingToDiscard):
        authoring.discard_draft(published_quiz(), admin_id=ADMIN_ID)


def test_return_and_discard_are_audited():
    quiz = published_quiz()
    authoring.use_as_draft(quiz, quiz.revisions.get(), admin_id=ADMIN_ID)
    authoring.discard_draft(quiz, admin_id=ADMIN_ID)
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"quiz.revision_restored", "quiz.draft_discarded"} <= actions
    event = AuditEvent.objects.get(action="quiz.revision_restored")
    assert event.details_json["revision_no"] == 1


def test_returned_revision_with_uninstalled_type_is_a_publication_problem():
    quiz = published_quiz()
    old = quiz.revisions.get()
    snapshot = old.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=old.pk).update(snapshot_json=snapshot)
    old.refresh_from_db()
    authoring.use_as_draft(quiz, old, admin_id=ADMIN_ID)
    assert [p.code for p in authoring.validate_for_publication(quiz)] == ["type_unavailable"]


def test_discard_audit_names_the_revision():
    quiz = published_quiz()
    add_question(quiz)
    authoring.discard_draft(quiz, admin_id=ADMIN_ID)
    event = AuditEvent.objects.get(action="quiz.draft_discarded")
    assert event.details_json["revision_no"] == 2


def test_locales_to_fix_lists_languages_without_translation():
    question = authoring.editable_questions(_one_question(("cs", "en"), ("cs",)))[0]
    assert questions.locales_to_fix(question, ["cs", "en"]) == ["en"]


def test_complete_question_has_no_locales_to_fix():
    question = authoring.editable_questions(_one_question(("cs", "en"), ("cs", "en")))[0]
    assert questions.locales_to_fix(question, ["cs", "en"]) == []


def _one_question(quiz_locales, question_locales):
    quiz = make_quiz(locales=quiz_locales)
    authoring.save_question(quiz, None, "choice", definition(question_locales))
    return quiz


def test_explanation_filled_in_one_language_blocks_publication(db):
    quiz = make_quiz(locales=("cs", "uk"))
    authoring.save_question(
        quiz, None, "choice", definition(("cs", "uk")), explanation={"cs": "Protože"}
    )
    problems = authoring.validate_for_publication(quiz)
    assert [(p.code, p.locale) for p in problems] == [("explanation_missing", "uk")]
    assert questions.locales_to_fix(authoring.editable_questions(quiz)[0], ["cs", "uk"]) == ["uk"]


def test_no_explanation_publishes(db):
    quiz = make_quiz(locales=("cs", "uk"))
    authoring.save_question(quiz, None, "choice", definition(("cs", "uk")))
    assert authoring.validate_for_publication(quiz) == []


def test_explanation_in_no_quiz_language_is_no_gap():
    question = {"explanation": {"en": "Because"}}
    assert questions.explanation_gaps(question, ["cs"]) == []
    assert questions.explanation_gaps(question, ["cs", "en"]) == ["cs"]
    assert questions.explanation_gaps({}, ["cs"]) == []


NO_COPY = {"asset": None, "source": "https://a.example/1.png", "alt": {"cs": "Popis"}}


def _with_image_without_copy(quiz, **setting_values):
    config = definition(("cs",)) | {"image": NO_COPY}
    return authoring.save_question(
        quiz, None, "choice", config, setting_values=setting_values or None
    )


def test_copy_mode_blocks_an_image_with_no_copy():
    quiz = make_quiz()
    _with_image_without_copy(quiz)
    problems = authoring.validate_for_publication(quiz)
    assert [(p.question_no, p.code) for p in problems] == [(1, "image_no_copy")]


def test_external_mode_does_not_block_it():
    quiz = make_quiz()
    _with_image_without_copy(quiz)
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    assert authoring.validate_for_publication(quiz) == []


def test_a_question_value_decides_for_that_question():
    quiz = make_quiz()
    _with_image_without_copy(quiz, **{EXTERNAL_IMAGE_MODE: "external"})
    assert authoring.validate_for_publication(quiz) == []
    settings.set_override(EXTERNAL_IMAGE_MODE, quiz, "external", admin_id=ADMIN_ID)
    _with_image_without_copy(quiz, **{EXTERNAL_IMAGE_MODE: "copy"})
    codes = [p.code for p in authoring.validate_for_publication(quiz)]
    assert codes == ["image_no_copy"]


def test_a_copy_never_blocks():
    quiz = make_quiz()
    image = {"asset": "abc", "source": "https://a.example/1.png", "alt": {"cs": "Popis"}}
    authoring.save_question(quiz, None, "choice", definition(("cs",)) | {"image": image})
    assert authoring.validate_for_publication(quiz) == []


def test_a_later_mode_change_leaves_a_published_quiz_alone():
    quiz = make_quiz()
    _with_image_without_copy(quiz, **{EXTERNAL_IMAGE_MODE: "external"})
    publish(quiz)
    settings.set_global(EXTERNAL_IMAGE_MODE, "copy", admin_id=ADMIN_ID)
    assert authoring.latest_published(quiz) is not None
    assert not authoring.has_draft(quiz)


def test_duplicate_copies_the_type_and_the_quiz_settings_but_not_branding():
    quiz = make_quiz(quiz_type="contest")
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "20", admin_id=ADMIN_ID)
    settings.set_override(settings.GRADING_VIEW, quiz, "by_attempt", admin_id=ADMIN_ID)
    palette = settings.CATALOGUE["color_palette"]
    chosen = next(choice for choice in palette.choices if choice != palette.default)
    settings.set_override("color_palette", quiz, chosen, admin_id=ADMIN_ID)
    BrandingConfiguration.objects.create(quiz=quiz, theme_id="default")
    copy = authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    assert copy.quiz_type == "contest"
    assert dict(AppSetting.objects.filter(quiz=copy).values_list("key", "value_json")) == {
        settings.ATTEMPT_LIMIT: "20",
        settings.GRADING_VIEW: "by_attempt",
        "color_palette": chosen,
    }
    assert not BrandingConfiguration.objects.filter(quiz=copy).exists()
    assert AppSetting.objects.filter(quiz=quiz).count() == 3
