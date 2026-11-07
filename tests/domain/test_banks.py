import pytest

from app.domain import authoring, banks
from app.domain.models import BankQuestion, QuestionBank
from tests.domain.helpers import (
    ADMIN_ID,
    add_bank_question,
    add_question,
    add_row,
    bank_with,
    definition,
    make_bank,
    make_quiz,
)

pytestmark = pytest.mark.django_db
ALL = ("cs", "en", "uk")


def stored(question_id):
    return BankQuestion.objects.get(pk=question_id)


def test_question_needs_one_complete_language():
    bank = make_bank()
    config = definition(("cs",))
    config["prompt"] = {}
    with pytest.raises(banks.NoCompleteLanguage):
        banks.save_question(bank, None, "choice", config, locales=ALL, tags=())
    assert not BankQuestion.objects.exists()


def test_tags_are_trimmed_and_compared_ignoring_case():
    bank = make_bank()
    add_bank_question(bank, tags=(" 20. století ", "Středověk"))
    add_bank_question(bank, tags=("středověk",))
    assert stored(BankQuestion.objects.first().pk).tags == ["20. století", "Středověk"]
    row = {"bank_id": str(bank.id), "tag": "STŘEDOVĚK ", "points": 1}
    assert banks.usable_count(row, ["cs"]) == (2, 2)
    assert banks.tags_of(bank) == ["20. století", "Středověk"]


def test_incomplete_explanation_makes_a_language_incomplete():
    bank = make_bank()
    add_bank_question(bank, locales=("cs", "uk"), explanation={"cs": "Protože"})
    row = {"bank_id": str(bank.id), "tag": "", "points": 1}
    assert banks.usable_count(row, ["uk"]) == (0, 1)
    assert banks.usable_count(row, ["cs"]) == (1, 1)


def test_complete_languages_are_listed():
    bank = make_bank()
    question_id = add_bank_question(bank, locales=("cs", "uk"))
    assert banks.complete_locales(stored(question_id), ALL) == ["cs", "uk"]


def test_bank_in_use_cannot_be_deleted_and_names_the_quiz():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank)
    with pytest.raises(banks.BankInUse) as error:
        banks.delete(bank, admin_id=ADMIN_ID)
    assert quiz.slug in error.value.quizzes
    assert QuestionBank.objects.filter(pk=bank.pk).exists()


def test_unused_bank_is_deleted_with_its_questions():
    bank = bank_with(2)
    banks.delete(bank, admin_id=ADMIN_ID)
    assert not QuestionBank.objects.exists()
    assert not BankQuestion.objects.exists()


def test_bank_used_only_by_an_old_revision_can_be_deleted():
    bank = bank_with(1)
    quiz = make_quiz()
    add_question(quiz)
    row = add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.delete_draw(quiz, row)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    banks.delete(bank, admin_id=ADMIN_ID)
    assert not QuestionBank.objects.exists()


def test_deleting_a_question_leaves_published_revisions_unchanged():
    bank = bank_with(2)
    quiz = make_quiz()
    add_row(quiz, bank, count=1)
    revision = authoring.publish(quiz, admin_id=ADMIN_ID)
    before = revision.snapshot_json
    banks.delete_question(bank, BankQuestion.objects.first().pk, admin_id=ADMIN_ID)
    revision.refresh_from_db()
    assert revision.snapshot_json == before


def test_second_save_with_one_new_id_updates():
    bank = make_bank()
    for prompt in ("První", "Druhý"):
        banks.save_question(
            bank,
            None,
            "choice",
            definition(("cs",), prompt=prompt),
            locales=ALL,
            tags=(),
            new_id="01a1b4c1-5764-77ef-8a6f-fca78cc7f734",
        )
    only = BankQuestion.objects.get()
    assert only.question_json["definition"]["prompt"]["cs"].startswith("Druhý")
    assert only.question_json["id"] == str(only.pk)


def test_bank_of_an_archived_quiz_cannot_be_deleted():
    """Restoring the quiz would leave it blocked by a row whose bank is gone."""
    bank = bank_with(1)
    quiz = make_quiz(slug="archivovany")
    add_row(quiz, bank)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    with pytest.raises(banks.BankInUse) as error:
        banks.delete(bank, admin_id=ADMIN_ID)
    assert error.value.quizzes == ["archivovany"]
