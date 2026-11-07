"""What settings and pages do with stored answers (AC-59)."""

import pytest

from app.domain import attempts, settings
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, OPTION_A, make_quiz, open_quiz_run
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def behaviour(quiz, **values):
    return {"slug": quiz.slug, **values}


def test_run_counts_include_pending(logged_in):
    run = open_quiz_run()
    Attempt.objects.create(
        run=run, revision=run.current_revision, status=Attempt.Status.PENDING_GRADING
    )
    Attempt.objects.create(run=run, revision=run.current_revision, status=Attempt.Status.SUBMITTED)
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert "2" in html
    assert text(logged_in.get(f"/admin/quizzes/{run.quiz.id}/runs")).count("2") >= 1


def test_quiz_form_refuses_public_without_all(logged_in):
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        behaviour(quiz, answers_visibility="public", store_answers="images"),
    )
    assert "ukládat všechny" in text(response)
    assert settings.quiz_override(settings.ANSWERS_VISIBILITY, quiz) is None


def test_quiz_form_takes_public_with_all(logged_in):
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        behaviour(quiz, answers_visibility="public", store_answers="all"),
    )
    assert response.status_code == 302
    assert settings.answers_visibility(quiz) == "public"


def test_global_conflict_behaves_as_admins_and_warns(logged_in):
    quiz = make_quiz()
    settings.set_global(settings.STORE_ANSWERS, "all", admin_id=ADMIN_ID)
    settings.set_override(settings.ANSWERS_VISIBILITY, quiz, "public", admin_id=ADMIN_ID)
    assert settings.answers_visibility(quiz) == "public"
    settings.set_global(settings.STORE_ANSWERS, "images", admin_id=ADMIN_ID)
    assert settings.answers_visibility(quiz) == "admins"
    assert "ukládá jen fotky" in text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))


def test_global_form_offers_the_settings_and_refuses_the_conflict(logged_in):
    html = text(logged_in.get("/admin/settings"))
    assert 'name="store_answers"' in html and 'name="grading_view"' in html
    response = logged_in.post(
        "/admin/settings", {"store_answers": "images", "answers_visibility": "public"}
    )
    assert "ukládat všechny" in text(response)
    assert settings.resolve(settings.ANSWERS_VISIBILITY) == "admins"


def test_defaults_change_nothing_for_an_existing_quiz():
    run = open_quiz_run()
    client = FormClient()
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    attempt = Attempt.objects.get()
    question = attempts.questions_of(attempt)[0]
    result = text(
        client.post(
            f"/a/{attempt.id}/submit",
            {
                "attempt_token": field(html, "attempt_token"),
                "submission_key": field(html, "submission_key"),
                "lang": "cs",
                f"{question['id']}:options[]": [OPTION_A],
            },
        )
    )
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.SUBMITTED and attempt.score == 1
    assert attempt.answers.count() == 0
    assert "provisional" not in result and "předběžné" not in result
    assert "/v/" not in result
