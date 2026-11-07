import pytest
from django.utils import translation

from app.domain import authoring, revision_diff, settings
from app.domain.models import Quiz, QuizRevision
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_B,
    add_question,
    definition,
    make_quiz,
    published_quiz,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def compare(quiz):
    published = authoring.latest_published(quiz)
    return revision_diff.compare(
        published.snapshot_json if published else None,
        authoring.future_snapshot(quiz),
        revision_diff.locales_of(authoring.future_snapshot(quiz)),
    )


def row_keys(change):
    return {(row.label, row.locale) for row in change.rows}


def question_id(quiz, index=0):
    return authoring.editable_questions(quiz)[index]["id"]


def test_first_publication_shows_everything_as_added():
    quiz = make_quiz()
    add_question(quiz)
    diff = compare(quiz)
    assert len(diff.added) == 1 and diff.added[0].number == 1
    assert "Otázka cs" in {row.after for row in diff.added[0].rows}
    assert {row.before for row in diff.added[0].rows} == {None}
    assert not diff.is_empty


def test_changed_correct_answer_is_listed():
    quiz = published_quiz()
    add_question(quiz, OPTION_B, question_id=question_id(quiz))
    diff = compare(quiz)
    assert len(diff.changed) == 1
    rows = {row.label: row for row in diff.changed[0].rows}
    assert rows["Correct"].before == "1: Ano cs"
    assert rows["Correct"].after == "2: Ne cs"
    assert not diff.added and not diff.removed and not diff.moved


def test_changed_prompt_is_listed_with_its_language():
    quiz = published_quiz(locales=("cs", "uk"))
    add_question(quiz, prompt="Jiná", question_id=question_id(quiz))
    assert ("Question", "uk") in row_keys(compare(quiz).changed[0])


def test_added_removed_moved():
    quiz = published_quiz(questions=3)
    first, second, third = [q["id"] for q in authoring.editable_questions(quiz)]
    authoring.delete_question(quiz, first)
    add_question(quiz, prompt="Nová")
    draft = authoring.get_draft(quiz)
    questions = draft.snapshot_json["questions"]
    questions[0], questions[1] = questions[1], questions[0]
    draft.save()
    diff = compare(quiz)
    assert len(diff.removed) == 1 and len(diff.added) == 1
    assert sorted(change.number for change in diff.moved) == [1, 2]
    assert not diff.changed


def test_adding_a_question_at_the_end_moves_nothing():
    quiz = published_quiz(questions=2)
    add_question(quiz, prompt="Nová")
    assert compare(quiz).moved == []


def test_changed_points_and_scoring_are_listed():
    quiz = published_quiz()
    draft = authoring.get_draft(quiz)
    question = draft.snapshot_json["questions"][0]
    question["settings"]["points"] = 5
    question["scoring"] = "other"
    question["type_version"] = "9.9.9"
    draft.save()
    rows = {row.label: row for row in compare(quiz).changed[0].rows}
    assert (rows["Points"].before, rows["Points"].after) == ("1", "5")
    assert rows["Scoring"].after == "other"
    assert rows["Question type version"].after == "9.9.9"


def test_title_and_language_changes_are_listed():
    quiz = published_quiz()
    quiz.title = {"cs": "Nový", "uk": "Новий"}
    quiz.supported_locales = ["cs", "uk"]
    quiz.save()
    authoring.get_draft(quiz)
    fields = {(row.label, row.locale): row for row in compare(quiz).quiz_fields}
    assert fields[("Title", "cs")].after == "Nový"
    assert fields[("Title", "uk")].before is None
    assert fields[("Languages", None)].after == "cs, uk"


def test_changed_default_language_is_listed():
    quiz = published_quiz(locales=("cs", "uk"))
    quiz.default_locale = "uk"
    quiz.save()
    authoring.get_draft(quiz)
    labels = {row.label for row in compare(quiz).quiz_fields}
    assert "Default language" in labels


def test_equal_snapshots_are_empty():
    quiz = published_quiz()
    authoring.get_draft(quiz)
    assert compare(quiz).is_empty


def test_unavailable_type_does_not_break_comparison():
    quiz = published_quiz()
    published = quiz.revisions.get()
    snapshot = published.snapshot_json
    snapshot["questions"][0]["type"] = "gone.type"
    QuizRevision.objects.filter(pk=published.pk).update(snapshot_json=snapshot)
    add_question(quiz, OPTION_B, question_id=question_id(quiz))
    draft = authoring.get_draft(quiz)
    draft.snapshot_json["questions"][0]["type"] = "gone.type"
    draft.save()
    diff = compare(quiz)
    assert diff.changed[0].label == "gone.type"


def test_future_snapshot_has_what_publication_stores():
    quiz = published_quiz()
    add_question(quiz)
    snapshot = authoring.future_snapshot(Quiz.objects.get(pk=quiz.pk))
    assert snapshot["title"] == quiz.title and snapshot["locales"] == ["cs"]
    assert len(snapshot["questions"]) == 2
    assert (
        authoring.publish(quiz, admin_id=ADMIN_ID).snapshot_json["questions"][1]["id"]
        == (snapshot["questions"][1]["id"])
    )


def test_change_overview_lists_an_explanation_change():
    quiz = make_quiz()
    question = add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    stored = authoring.editable_questions(quiz)[0]
    authoring.save_question(
        quiz, question, stored["type"], stored["definition"], explanation={"cs": "Protože"}
    )
    rows = compare(quiz).changed[0].rows
    assert [(row.label, row.locale, row.after) for row in rows] == [
        ("Explanation", "cs", "Protože")
    ]


def test_a_changed_question_setting_appears_in_the_overview():
    quiz = published_quiz()
    question = question_id(quiz)
    authoring.save_question(
        quiz,
        question,
        "choice",
        definition(("cs",)),
        setting_values={settings.SHOW_SOURCES: "off"},
    )
    diff = compare(quiz)
    assert not diff.is_empty
    assert ("Sources on the result", None) in row_keys(diff.changed[0])
