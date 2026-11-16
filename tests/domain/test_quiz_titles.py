"""Two quizzes that are not archived never share a title in one language."""

import pytest

from app.domain import authoring
from app.domain.models import Quiz
from tests.domain.helpers import ADMIN_ID, make_quiz

pytestmark = pytest.mark.django_db


def titled(slug, **title):
    return Quiz.objects.create(
        slug=slug, title=title, default_locale="cs", supported_locales=["cs"]
    )


def test_a_title_is_taken_by_another_quiz_in_the_same_language_whatever_the_case():
    """AC-178: per language, case and spaces aside."""
    titled("evropa", cs="Evropský kvíz", en="European quiz")
    assert authoring.taken_titles({"cs": "  evropský   KVÍZ "}) == ["cs"]
    assert authoring.taken_titles({"en": "Evropský kvíz"}) == []  # another language
    assert authoring.taken_titles({"cs": "Evropa"}) == []


def test_a_quiz_does_not_clash_with_itself_nor_with_an_archived_one():
    own = titled("evropa", cs="Evropský kvíz")
    assert authoring.taken_titles({"cs": "Evropský kvíz"}, besides=own) == []
    own.archived_at = own.created_at
    own.save()
    assert authoring.taken_titles({"cs": "Evropský kvíz"}) == []


def test_a_duplicate_gets_a_free_title_marked_as_a_copy():
    quiz = titled("evropa", cs="Evropský kvíz", en="European quiz", uk="Європейська вікторина")
    first = authoring.duplicate_quiz(quiz, "evropa-copy", admin_id=ADMIN_ID)
    assert first.title == {
        "cs": "Evropský kvíz (kopie)",
        "en": "European quiz (copy)",
        "uk": "Європейська вікторина (копія)",
    }
    second = authoring.duplicate_quiz(quiz, "evropa-copy-2", admin_id=ADMIN_ID)
    assert second.title["cs"] == "Evropský kvíz (kopie 2)"
    assert second.title["en"] == "European quiz (copy 2)"


def test_restoring_from_the_archive_refuses_a_title_taken_meanwhile():
    old = titled("evropa", cs="Evropský kvíz")
    authoring.archive_quiz(old, admin_id=ADMIN_ID)
    titled("nova-evropa", cs="Evropský kvíz")
    with pytest.raises(authoring.TitleTaken) as refused:
        authoring.restore_quiz(old, admin_id=ADMIN_ID)
    assert refused.value.locales == ["cs"]
    old.refresh_from_db()
    assert old.archived_at is not None


def test_going_back_to_a_title_another_quiz_took_is_refused():
    quiz = titled("evropa", cs="Evropa")
    snapshot = {"title": {"cs": "Evropský kvíz"}, "locales": ["cs"], "default_locale": "cs"}
    titled("jina", cs="Evropský kvíz")
    with pytest.raises(authoring.TitleTaken):
        authoring._restore_quiz_fields(quiz, snapshot)
    quiz.refresh_from_db()
    assert quiz.title == {"cs": "Evropa"}


def test_free_title_without_the_copy_mark_numbers_the_title():
    make_quiz("kviz")  # "Název cs"
    assert authoring.free_title({"cs": "Název cs"}) == {"cs": "Název cs (2)"}
    assert authoring.free_title({"cs": "Volný"}) == {"cs": "Volný"}


def test_a_duplicate_keeps_the_public_address():
    quiz = titled("evropa", cs="Evropa")
    quiz.public_origin = "https://kviz.example.cz"
    quiz.save()
    copied = authoring.duplicate_quiz(quiz, "evropa-copy", admin_id=ADMIN_ID)
    assert copied.public_origin == "https://kviz.example.cz"


def test_quizzes_that_already_share_a_title_can_still_go_back_and_discard():
    """Only a title that changes is checked: older duplicates are not locked."""
    quiz = titled("evropa", cs="Evropa")
    titled("jina", cs="Evropa")  # from before the rule
    snapshot = {"title": {"cs": "evropa "}, "locales": ["cs"], "default_locale": "cs"}
    authoring._restore_quiz_fields(quiz, snapshot)  # same title, other spelling: no refusal
    assert authoring.new_titles({"cs": "Evropa", "en": "Europe"}, quiz) == {"en": "Europe"}


def test_a_copy_of_an_archived_quiz_is_still_marked_as_a_copy():
    quiz = titled("evropa", cs="Evropa")
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    copied = authoring.duplicate_quiz(quiz, "evropa-copy", admin_id=ADMIN_ID)
    assert copied.title == {"cs": "Evropa (kopie)"}


def test_a_long_title_is_shortened_so_the_mark_fits():
    long = "x" * 200
    titled("dlouhy", cs=long)
    marked = authoring.free_title({"cs": long}, copy_mark=True)["cs"]
    assert len(marked) <= authoring.MAX_TITLE and marked.endswith(" (kopie)")


def test_twenty_copies_in_a_row_get_twenty_distinct_titles():
    quiz = titled("evropa", cs="Evropa")
    titles = [
        authoring.duplicate_quiz(quiz, f"kopie-{n}", admin_id=ADMIN_ID).title["cs"]
        for n in range(20)
    ]
    assert titles[0] == "Evropa (kopie)" and titles[-1] == "Evropa (kopie 20)"
    assert len(set(titles)) == 20


def test_a_title_taken_in_one_language_numbers_every_language_alike():
    titled("jiny", cs="Jiný", en="Quiz")
    assert authoring.free_title({"cs": "Kvíz", "en": "Quiz"}) == {
        "cs": "Kvíz (2)",
        "en": "Quiz (2)",
    }
