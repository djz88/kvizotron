import pytest

from app.domain import authoring
from app.domain.models import Quiz, QuizRevision
from app.kernel.models import AuditEvent
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, open_quiz_run, published_quiz

pytestmark = pytest.mark.django_db
Status = QuizRevision.Status


def ids(questions):
    return [question["id"] for question in questions]


def test_duplicate_copies_title_languages_and_questions_as_draft():
    """The title is copied in every language, marked as a copy so the two stay apart."""
    quiz = published_quiz(locales=("cs", "uk"), questions=2)
    add_question(quiz, prompt="Rozepsaná")
    copy = authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    assert copy.id != quiz.id and copy.slug == "kopie"
    assert copy.title == {"cs": "Název cs (kopie)", "uk": "Název uk (копія)"}
    assert copy.supported_locales == ["cs", "uk"] and copy.default_locale == "cs"
    draft = copy.revisions.get()
    assert draft.status == Status.DRAFT and draft.revision_no == 1
    assert ids(draft.snapshot_json["questions"]) == ids(authoring.editable_questions(quiz))


def test_duplicate_has_no_revisions_rounds_or_attempts_and_featured_off():
    run = open_quiz_run(featured=True)
    copy = authoring.duplicate_quiz(run.quiz, "kopie", admin_id=ADMIN_ID)
    assert copy.featured is False
    assert copy.revisions.count() == 1 and not copy.runs.exists()
    assert not copy.revisions.filter(status=Status.PUBLISHED).exists()


def test_duplicate_does_not_share_questions_with_the_original():
    quiz = published_quiz()
    copy = authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    add_question(copy, prompt="Jen v kopii")
    assert len(authoring.editable_questions(quiz)) == 1


def test_duplicate_of_archived_copies_draft_else_highest_archived():
    plain = published_quiz("a")
    authoring.archive_quiz(plain, admin_id=ADMIN_ID)
    assert (
        len(
            authoring.duplicate_quiz(plain, "a2", admin_id=ADMIN_ID)
            .revisions.get()
            .snapshot_json["questions"]
        )
        == 1
    )
    with_draft = published_quiz("b")
    add_question(with_draft, prompt="Rozepsaná")
    authoring.archive_quiz(with_draft, admin_id=ADMIN_ID)
    copy = authoring.duplicate_quiz(with_draft, "b2", admin_id=ADMIN_ID)
    assert len(copy.revisions.get().snapshot_json["questions"]) == 2


def test_duplicate_with_taken_slug_is_refused():
    quiz = published_quiz()
    with pytest.raises(authoring.SlugTaken):
        authoring.duplicate_quiz(quiz, quiz.slug, admin_id=ADMIN_ID)
    assert Quiz.objects.count() == 1


def test_archive_with_open_round_is_refused():
    run = open_quiz_run()
    with pytest.raises(authoring.RunStillOpen):
        authoring.archive_quiz(run.quiz, admin_id=ADMIN_ID)
    run.quiz.refresh_from_db()
    assert run.quiz.archived_at is None


def test_archive_turns_published_into_archived():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    assert quiz.archived_at is not None
    assert quiz.revisions.get().status == Status.ARCHIVED


def test_archive_keeps_draft_untouched():
    quiz = published_quiz()
    add_question(quiz, prompt="Rozepsaná")
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    draft = quiz.revisions.get(status=Status.DRAFT)
    assert len(draft.snapshot_json["questions"]) == 2


@pytest.mark.parametrize(
    "action",
    [
        lambda quiz: authoring.get_draft(quiz),
        lambda quiz: add_question(quiz),
        lambda quiz: authoring.delete_question(quiz, "x"),
        lambda quiz: authoring.publish(quiz, admin_id=ADMIN_ID),
        lambda quiz: authoring.open_run(quiz, admin_id=ADMIN_ID),
        lambda quiz: authoring.use_as_draft(quiz, quiz.revisions.get(), admin_id=ADMIN_ID),
        lambda quiz: authoring.discard_draft(quiz, admin_id=ADMIN_ID),
    ],
    ids=["draft", "save", "delete", "publish", "open_run", "return", "discard"],
)
def test_archived_quiz_refuses_editing(action):
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        action(quiz)


def test_stale_object_is_refused_too():
    quiz = published_quiz()
    authoring.archive_quiz(Quiz.objects.get(pk=quiz.pk), admin_id=ADMIN_ID)
    with pytest.raises(authoring.QuizArchived):
        add_question(quiz)


def test_restore_returns_highest_archived_to_published():
    quiz = published_quiz()
    add_question(quiz, prompt="Druhá")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    quiz.refresh_from_db()
    assert quiz.archived_at is None
    assert quiz.revisions.get(revision_no=2).status == Status.PUBLISHED
    assert quiz.revisions.get(revision_no=1).status == Status.SUPERSEDED


def test_restore_makes_draft_editable_again():
    quiz = published_quiz()
    add_question(quiz, prompt="Rozepsaná")
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    add_question(quiz, prompt="Další")
    assert len(authoring.editable_questions(quiz)) == 3
    assert authoring.publish(quiz, admin_id=ADMIN_ID).revision_no == 2


def test_archive_of_never_published_quiz_works():
    quiz = make_quiz()
    add_question(quiz)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    assert quiz.revisions.get().status == Status.DRAFT


def test_archive_and_restore_do_not_change_revision_content():
    quiz = published_quiz()
    revision = quiz.revisions.get()
    frozen = (revision.checksum, revision.snapshot_json)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    revision.refresh_from_db()
    assert (revision.checksum, revision.snapshot_json) == frozen


def test_all_are_audited():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    authoring.duplicate_quiz(quiz, "kopie", admin_id=ADMIN_ID)
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"quiz.archived", "quiz.restored", "quiz.duplicated"} <= actions


def test_restoring_a_quiz_that_is_not_archived_changes_nothing():
    quiz = published_quiz()
    authoring.restore_quiz(quiz, admin_id=ADMIN_ID)
    assert not AuditEvent.objects.filter(action="quiz.restored").exists()
