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


def test_language_counts():
    """AC-162: the languages a bank has, with the number of questions complete in each."""
    bank = make_bank()
    add_bank_question(bank, locales=("cs",))
    add_bank_question(bank, locales=("cs", "uk"))
    assert banks.language_counts(bank, ALL) == {"cs": 2, "uk": 1}
    assert banks.language_counts(make_bank("Prázdná"), ALL) == {}


def test_levels_of_defaults_to_normal_and_ignores_case():
    """AC-163: a question with no level tag counts as normal; case and spaces do not matter."""
    assert banks.levels_of(["EU"]) == {"normal"}
    assert banks.levels_of([]) == {"normal"}
    assert banks.levels_of([" Hard "]) == {"hard"}
    assert banks.levels_of(["easy", "EU"]) == {"easy"}


def test_two_levels_on_one_question_are_refused():
    """AC-164: a question has at most one of the level tags."""
    with pytest.raises(banks.MoreThanOneLevel):
        banks.check_one_level(["easy", "hard"])
    banks.check_one_level(["easy", "EASY"])
    banks.check_one_level(["EU"])
    bank = make_bank()
    with pytest.raises(banks.MoreThanOneLevel):
        add_bank_question(bank, tags=("easy", "hard"))
    assert not BankQuestion.objects.exists()


def level_bank():
    bank = make_bank()
    for tags in (("easy",), ("hard",), ("EU",), ("normal",)):
        add_bank_question(bank, tags=tags)
    return bank


def level_row(bank, difficulty=None, **fields):
    row = {"bank_id": str(bank.id), "tag": "", "points": 1} | fields
    if difficulty is not None:
        row["difficulty"] = difficulty
    return row


@pytest.mark.parametrize(
    ("difficulty", "expected"),
    [("easy", 1), ("hard", 1), ("normal", 2), ("", 4), (None, 4)],
)
def test_a_row_with_a_level_draws_only_that_level(difficulty, expected):
    """AC-163: a level on the row keeps only the questions of that level."""
    row = level_row(level_bank(), difficulty)
    assert banks.usable_count(row, ["cs"]) == (expected, expected)
    assert len(banks.pool(row, ["cs"])) == expected


def test_level_and_tag_must_both_match():
    bank = make_bank()
    add_bank_question(bank, tags=("EU", "easy"))
    add_bank_question(bank, tags=("US", "easy"))
    assert banks.usable_count(level_row(bank, "easy", tag="EU"), ["cs"]) == (1, 1)


def test_a_question_with_two_level_tags_saved_earlier_matches_both():
    bank = make_bank()
    question_id = add_bank_question(bank)
    BankQuestion.objects.filter(pk=question_id).update(tags=["easy", "hard"])
    assert banks.usable_count(level_row(bank, "easy"), ["cs"]) == (1, 1)
    assert banks.usable_count(level_row(bank, "hard"), ["cs"]) == (1, 1)
    assert banks.usable_count(level_row(bank, "normal"), ["cs"]) == (0, 0)


def test_level_choices_start_with_the_random_mix():
    assert [value for value, _label in banks.level_choices()] == ["", "easy", "normal", "hard"]
    assert banks.level_label("") == ""
    assert banks.level_label("hard") == dict(banks.level_choices())["hard"]


def test_level_labels_live_in_their_own_translation_context():
    from django.utils.translation import gettext, override

    with override("cs"):
        assert banks.level_label("normal") == "Normální"
        assert gettext("Normal") == "Normal"  # the bare word is not taken by the level label


def test_used_by_names_the_quizzes_that_draw_from_a_bank():
    bank = bank_with(1)
    assert banks.used_by(bank) == []
    add_row(make_quiz(slug="kviz-a"), bank)
    assert banks.used_by(bank) == ["kviz-a"]
