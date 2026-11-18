"""AC-185: the result page lists sources by the run's value, a preview by the quiz's."""

import pytest

from app.domain import attempts, authoring, settings
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, definition, make_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def open_run(*, question_setting=None):
    quiz = make_quiz()
    authoring.save_question(
        quiz,
        None,
        "choice",
        definition(("cs",)),
        sources=["Kniha"],
        setting_values=question_setting or {},
    )
    authoring.publish(quiz, admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID)


def result_after(run, *, quiz_value=None):
    client = FormClient()
    html = client.post(f"/r/{run.id}/start", {"lang": "cs"}).content.decode()
    if quiz_value:
        settings.set_override(settings.SHOW_SOURCES, run.quiz, quiz_value, admin_id=ADMIN_ID)
    attempt = Attempt.objects.get()
    question = attempts.questions_of(attempt)[0]
    return client.post(
        f"/a/{attempt.id}/submit",
        {
            "attempt_token": html.split('name="attempt_token" value="')[1].split('"')[0],
            "submission_key": html.split('name="submission_key" value="')[1].split('"')[0],
            "lang": "cs",
            f"{question['id']}:options[]": ["aaaa1111"],
        },
    ).content.decode()


def test_the_result_after_submit_lists_sources_by_the_run():
    """AC-185: the page returned by the submit follows the run, not the changed quiz."""
    assert "Kniha" in result_after(open_run(), quiz_value="off")


def test_a_question_setting_still_hides_sources():
    """AC-185: a question with its own off keeps its sources out of the result."""
    run = open_run(question_setting={settings.SHOW_SOURCES: "off"})
    assert "Kniha" not in result_after(run)


def test_a_question_setting_still_shows_sources_when_the_run_hides_them():
    """AC-185: a question's own on wins over the run's off."""
    settings.set_global(settings.SHOW_SOURCES, "off", admin_id=ADMIN_ID)
    run = open_run(question_setting={settings.SHOW_SOURCES: "on"})
    assert "Kniha" in result_after(run)


def test_a_preview_result_follows_the_quiz(logged_in):
    """AC-185: a preview has no run and reads the quiz as it is now."""
    quiz = make_quiz(locales=("cs", "en"))
    authoring.save_question(quiz, None, "choice", definition(("cs", "en")), sources=["Kniha"])
    authoring.publish(quiz, admin_id=ADMIN_ID)
    html = logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en").content.decode()
    token = html.split('name="attempt_token" value="')[1].split('"')[0]
    settings.set_override(settings.SHOW_SOURCES, quiz, "off", admin_id=ADMIN_ID)

    off = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit", {"attempt_token": token, "lang": "en"}
    ).content.decode()
    settings.set_override(settings.SHOW_SOURCES, quiz, "on", admin_id=ADMIN_ID)
    html = logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en").content.decode()
    token = html.split('name="attempt_token" value="')[1].split('"')[0]
    on = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit", {"attempt_token": token, "lang": "en"}
    ).content.decode()

    assert "Kniha" not in off
    assert "Kniha" in on
