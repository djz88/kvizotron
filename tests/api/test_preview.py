"""A preview plays like the real thing and stores nothing (AC-45)."""

import pytest
from django.apps import apps
from django.test import Client

from app.domain import authoring, settings
from app.domain.models import Attempt
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    add_question,
    add_row,
    bank_with,
    make_quiz,
    open_quiz_run,
    published_quiz,
)
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def row_counts():
    return {model.__name__: model._base_manager.count() for model in apps.get_models()}


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def submit(client, quiz, html, answers=None):
    return client.post(
        f"/admin/quizzes/{quiz.id}/preview/submit",
        {"attempt_token": field(html, "attempt_token"), "lang": "en", **(answers or {})},
    )


def question_ids(html):
    return [piece.split('"')[0] for piece in html.split('data-question="')[1:]]


@pytest.mark.parametrize("navigation", [mode.value for mode in settings.Navigation])
def test_clicking_through_stores_nothing(logged_in, navigation):
    quiz = published_quiz(locales=("cs", "en"))
    add_question(quiz, prompt="Koncept")
    settings.set_override(settings.NAVIGATION_MODE, quiz, navigation, admin_id=ADMIN_ID)
    settings.set_override(
        settings.REVEAL_MOMENT,
        quiz,
        settings.RevealMoment.AFTER_EACH
        if navigation != settings.Navigation.ALL_AT_ONCE
        else settings.RevealMoment.AT_END,
        admin_id=ADMIN_ID,
    )
    before = row_counts()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "Koncept en" in html
    ids = question_ids(html)
    if navigation != settings.Navigation.ALL_AT_ONCE:
        check = logged_in.post(
            f"/admin/quizzes/{quiz.id}/preview/check",
            {
                "attempt_token": field(html, "attempt_token"),
                "check_question": ids[0],
                f"{ids[0]}:options[]": [OPTION_A],
                "lang": "en",
            },
        )
        assert "reveal" in text(check)
    result = submit(logged_in, quiz, html, {f"{ids[0]}:options[]": [OPTION_A]})
    assert "Your score" in text(result)
    assert row_counts() == before
    assert not Attempt.objects.exists()


def test_older_revision_opens_with_its_own_content(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    first = authoring.latest_published(quiz).revision_no
    add_question(quiz, prompt="Nová")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview/{first}?lang=en"))
    assert "Nová" not in html
    assert len(question_ids(html)) == 1
    result = submit(logged_in, quiz, html)
    assert result.status_code == 200
    assert "Your score" in text(result)


def test_unknown_revision_is_404(logged_in):
    quiz = published_quiz()
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/preview/99").status_code == 404


def test_refused_without_login():
    quiz = published_quiz()
    client = FormClient()
    assert client.get(f"/admin/quizzes/{quiz.id}/preview").status_code == 302
    assert client.post(f"/admin/quizzes/{quiz.id}/preview/submit").status_code == 302
    assert client.post(f"/admin/quizzes/{quiz.id}/preview/check").status_code == 302


def test_no_run_is_needed_and_public_address_is_not_opened(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/preview").status_code == 200
    assert FormClient().get(f"/q/{quiz.slug}").status_code == 404


def test_draft_problems_listed_on_top(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    quiz.title = {}
    quiz.save()
    add_question(quiz)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "title is missing" in html


def test_question_lacking_this_language_says_so_and_rest_plays(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    add_question(quiz, prompt="Dobrá")
    broken = add_question(quiz, prompt="Vadná")
    questions = authoring.editable_questions(quiz)
    config = questions[1]["definition"]
    config["prompt"]["en"] = ""
    authoring.save_question(quiz, broken, "choice", config)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "This question cannot be shown yet" in html
    assert "Dobrá en" in html
    assert "Your score" in text(submit(logged_in, quiz, html))


def test_question_without_correct_answer_says_so_and_rest_plays(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    add_question(quiz, prompt="Dobrá")
    bad = add_question(quiz, prompt="Bez odpovědi")
    config = authoring.editable_questions(quiz)[1]["definition"]
    config["correct"] = ["neexistuje"]
    authoring.save_question(quiz, bad, "choice", config)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "This question cannot be shown yet" in html
    ids = question_ids(html)
    answers = {f"{ids[0]}:options[]": [OPTION_A]}
    assert "1 / 1" in text(submit(logged_in, quiz, html, answers))


def test_empty_draft_points_to_editor(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    response = logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en")
    assert response.status_code == 200
    assert "no questions" in text(response)
    assert f"/admin/quizzes/{quiz.id}/edit" in text(response)


def test_draw_row_that_cannot_be_filled_is_a_problem_not_a_server_error(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    bank = bank_with(1, locales=("cs", "en"))
    add_row(quiz, bank, count=1)
    bank.questions.all().delete()
    response = logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en")
    assert response.status_code == 200
    assert 'role="alert"' in text(response)


def test_draft_changed_under_open_preview_offers_restart(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    add_question(quiz)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    add_question(quiz, prompt="Později")
    response = text(submit(logged_in, quiz, html))
    assert "The draft changed" in response
    assert f"/admin/quizzes/{quiz.id}/preview" in response
    assert "Your score" not in response


def test_each_opening_draws_anew(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    add_row(quiz, bank_with(6, locales=("cs", "en")), count=1)
    seen = set()
    for _ in range(25):
        html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
        seen.add(tuple(question_ids(html)))
    assert len(seen) > 1


def test_bar_on_every_step_with_way_back(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    mark = "Nothing is stored"
    assert mark in html
    assert f"/admin/quizzes/{quiz.id}/edit" in html
    result = text(submit(logged_in, quiz, html))
    assert mark in result
    assert "Back to quizzes" not in result


def test_reveal_follows_settings(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    check = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/check",
        {
            "attempt_token": field(html, "attempt_token"),
            "check_question": question_ids(html)[0],
            "lang": "en",
        },
    )
    assert check.status_code == 403
    assert "reveal-list" not in text(submit(logged_in, quiz, html))
    settings.set_override(
        settings.REVEAL_MOMENT, quiz, settings.RevealMoment.AT_END, admin_id=ADMIN_ID
    )
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "reveal-list" in text(submit(logged_in, quiz, html))


def test_answer_key_absent_before_reveal_is_allowed(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert '"correct"' not in html
    token = field(html, "attempt_token")
    assert "correct" not in token


def test_tampered_token_is_refused(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit", {"attempt_token": "x", "lang": "en"}
    )
    assert "Your score" not in text(response)


def test_token_of_another_quiz_is_refused(logged_in):
    first = published_quiz("a", locales=("cs", "en"))
    second = published_quiz("b", locales=("cs", "en"))
    html = text(logged_in.get(f"/admin/quizzes/{first.id}/preview?lang=en"))
    assert "Your score" not in text(submit(logged_in, second, html))


def test_submit_requires_csrf(admin_user):
    quiz = published_quiz()
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    response = client.post(
        f"/admin/quizzes/{quiz.id}/preview/submit",
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 403


def test_public_page_output_keeps_its_addresses():
    run = open_quiz_run()
    html = text(FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}))
    assert "/submit" in html
    assert 'id="revision-notice"' in html
    assert "csrfmiddlewaretoken" not in html


def test_action_links_exist(logged_in):
    quiz = published_quiz(locales=("cs", "en"))
    edit = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f"/admin/quizzes/{quiz.id}/preview" in edit
    revisions = text(logged_in.get(f"/admin/quizzes/{quiz.id}/revisions"))
    assert f"/admin/quizzes/{quiz.id}/preview/1" in revisions
