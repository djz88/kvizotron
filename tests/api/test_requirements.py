"""What an admin sees of a module's requirements (AC-61)."""

import pytest

from app.domain import settings
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz
from tests.support.requirements import REASON, needs_reveal_at_end

pytestmark = pytest.mark.django_db
KEY = settings.REVEAL_MOMENT


def text(response):
    return response.content.decode()


def needing(quiz=None):
    if quiz is None:
        quiz = make_quiz()
        add_question(quiz)
    settings.set_override(KEY, quiz, "after_each", admin_id=ADMIN_ID)
    return quiz


def use_url(quiz):
    return f"/admin/quizzes/{quiz.id}/requirements/use"


def test_editor_shows_requirement_and_use_button(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/questions/new?type=choice"))
    assert REASON in html and use_url(quiz) in html
    assert f'name="key" value="{KEY}"' in html


def test_type_without_a_requirement_shows_nothing(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/questions/new?type=matching"))
    assert REASON not in html


def test_met_requirement_shows_nothing(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/questions/new?type=choice"))
    assert REASON not in html


def test_quiz_header_shows_what_is_unmet(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert REASON in html and use_url(quiz) in html


def test_use_sets_the_override_and_goes_back(logged_in):
    quiz = needing()
    back = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": KEY, "next": back})
    assert response.status_code == 302 and response["Location"] == back
    assert settings.quiz_override(KEY, quiz) == "at_end"


def test_use_does_not_go_to_another_site(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": KEY, "next": "https://example.org/"})
    assert response.status_code == 302 and "example.org" not in response["Location"]


def test_use_refuses_an_unknown_key(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        response = logged_in.post(use_url(quiz), {"key": settings.COLOR_PALETTE})
    assert response.status_code == 400
    assert settings.quiz_override(settings.COLOR_PALETTE, quiz) is None


def test_use_needs_login(client):
    quiz = needing()
    with needs_reveal_at_end():
        response = client.post(use_url(quiz), {"key": KEY})
    assert response.status_code == 302 and "/admin/login" in response["Location"]
    assert settings.quiz_override(KEY, quiz) == "after_each"


def test_publish_page_lists_the_reason(logged_in):
    quiz = needing()
    with needs_reveal_at_end():
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish"))
    assert REASON in html


def test_run_open_shows_the_reason(logged_in):
    quiz = needing(published_quiz())
    with needs_reveal_at_end():
        html = text(logged_in.post(f"/admin/quizzes/{quiz.id}/runs"))
    assert REASON in html
    assert not quiz.runs.exists()
