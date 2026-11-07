import pytest

from app.domain import attempts, authoring
from app.domain.models import QuizRevision
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_B,
    add_question,
    make_quiz,
    open_quiz_run,
    published_quiz,
)

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def base(quiz):
    return f"/admin/quizzes/{quiz.id}"


def two_revisions():
    quiz = published_quiz()
    add_question(quiz, OPTION_B, question_id=authoring.editable_questions(quiz)[0]["id"])
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return quiz


def test_revisions_page_requires_login(client):
    assert client.get(f"{base(make_quiz())}/revisions").status_code == 302


def test_edit_page_links_to_revisions(logged_in):
    quiz = make_quiz()
    assert f'href="{base(quiz)}/revisions"' in text(logged_in.get(f"{base(quiz)}/edit"))


def test_revisions_page_lists_numbers_statuses_and_scores(logged_in):
    quiz = two_revisions()
    html = text(logged_in.get(f"{base(quiz)}/revisions?lang=en"))
    assert "Published" in html and "Superseded" in html
    assert f"{base(quiz)}/revisions/1/compare" in html
    assert f"{base(quiz)}/revisions/2/restore" in html
    assert ">1</td>" in html  # question count and max score of a one-question quiz


def test_runs_tab_lists_historical_runs_with_revisions_and_submitted_count(logged_in):
    run = open_quiz_run()
    started = attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    attempts.start(run)  # in progress does not count
    add_question(run.quiz, OPTION_B, question_id=authoring.editable_questions(run.quiz)[0]["id"])
    authoring.publish(run.quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    html = text(logged_in.get(f"{base(run.quiz)}/runs?lang=en"))
    assert f"/admin/runs/{run.id}" in html
    assert "1, 2" in html and ">1</td>" in html


def test_compare_shows_differences(logged_in):
    html = text(logged_in.get(f"{base(two_revisions())}/revisions/2/compare"))
    assert "1: Ano cs" in html and "2: Ne cs" in html


def test_compare_of_first_revision_shows_all_added(logged_in):
    html = text(logged_in.get(f"{base(published_quiz())}/revisions/1/compare?lang=en"))
    assert "Added questions" in html


def test_compare_unknown_number_is_404(logged_in):
    assert logged_in.get(f"{base(published_quiz())}/revisions/9/compare").status_code == 404


def test_compare_of_a_draft_is_404(logged_in):
    quiz = published_quiz()
    add_question(quiz)
    assert logged_in.get(f"{base(quiz)}/revisions/2/compare").status_code == 404


def test_restore_without_draft_acts_without_confirmation_page(logged_in):
    quiz = two_revisions()
    response = logged_in.post(f"{base(quiz)}/revisions/1/restore")
    assert response.status_code == 302
    draft = quiz.revisions.get(status=QuizRevision.Status.DRAFT)
    assert draft.snapshot_json["questions"][0]["definition"]["correct"] != [OPTION_B]


def test_restore_with_draft_asks_first(logged_in):
    quiz = two_revisions()
    add_question(quiz, prompt="Rozepsaná")
    response = logged_in.post(f"{base(quiz)}/revisions/1/restore")
    assert response.status_code == 200 and 'name="confirm"' in text(response)
    assert len(authoring.editable_questions(quiz)) == 2
    confirmed = logged_in.post(f"{base(quiz)}/revisions/1/restore", {"confirm": "1"})
    assert confirmed.status_code == 302
    assert len(authoring.editable_questions(quiz)) == 1


def test_get_on_restore_changes_nothing(logged_in):
    quiz = two_revisions()
    assert logged_in.get(f"{base(quiz)}/revisions/1/restore").status_code == 200
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_restore_of_a_draft_is_404(logged_in):
    quiz = published_quiz()
    add_question(quiz)
    assert logged_in.post(f"{base(quiz)}/revisions/2/restore").status_code == 404


def test_restore_of_other_quizs_revision_is_404(logged_in):
    two_revisions()
    other = published_quiz("jiny")
    assert logged_in.post(f"{base(other)}/revisions/2/restore").status_code == 404


def test_discard_asks_first(logged_in):
    quiz = published_quiz()
    add_question(quiz)
    response = logged_in.get(f"{base(quiz)}/draft/discard")
    assert response.status_code == 200 and "csrfmiddlewaretoken" in text(response)
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()
    assert logged_in.post(f"{base(quiz)}/draft/discard").status_code == 302
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_edit_page_offers_discard_only_when_it_can_work(logged_in):
    never = make_quiz("a")
    add_question(never)
    assert "draft/discard" not in text(logged_in.get(f"{base(never)}/edit"))
    quiz = published_quiz("b")
    assert "draft/discard" not in text(logged_in.get(f"{base(quiz)}/edit"))
    add_question(quiz)
    assert "draft/discard" in text(logged_in.get(f"{base(quiz)}/edit"))


def test_discard_refusal_is_explained_on_never_published_quiz(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    for response in (
        logged_in.post(f"{base(quiz)}/draft/discard"),
        logged_in.get(f"{base(quiz)}/draft/discard"),
    ):
        assert response.status_code == 200 and 'role="alert"' in text(response)
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()
