"""A preview plays like the real thing and stores nothing (AC-45, AC-75)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.apps import apps
from django.test import Client

from app.domain import authoring, settings
from app.domain.models import Attempt, Participant
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
from tests.support.clock import freeze

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


# Answers after each question need one question per step (ADR-0052).
WITHOUT_CHECK = (settings.Navigation.ALL_AT_ONCE, settings.Navigation.PAGES)


@pytest.mark.parametrize("navigation", [mode.value for mode in settings.Navigation])
def test_clicking_through_stores_nothing(logged_in, navigation):
    quiz = published_quiz(locales=("cs", "en"))
    add_question(quiz, prompt="Koncept")
    settings.set_override(settings.NAVIGATION_MODE, quiz, navigation, admin_id=ADMIN_ID)
    settings.set_override(
        settings.REVEAL_MOMENT,
        quiz,
        settings.RevealMoment.AT_END
        if navigation in WITHOUT_CHECK
        else settings.RevealMoment.AFTER_EACH,
        admin_id=ADMIN_ID,
    )
    before = row_counts()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "Koncept en" in html
    ids = question_ids(html)
    if navigation not in WITHOUT_CHECK:
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


TIMED_NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def frozen(monkeypatch):
    """Ahead of `logged_in`, so the login is not older than the session allows."""
    freeze(monkeypatch, TIMED_NOW)


def limited_quiz():
    quiz = make_quiz(locales=("en",))
    add_question(quiz)
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "10", admin_id=None)
    return quiz


def preview_url(quiz):
    return f"/admin/quizzes/{quiz.id}/preview"


def test_preview_has_no_limit_by_default(logged_in):
    html = text(logged_in.get(preview_url(limited_quiz())))
    assert 'id="countdown"' not in html


def test_the_switch_is_offered_only_when_the_quiz_has_a_limit(logged_in):
    quiz = limited_quiz()
    assert "timed=1" in text(logged_in.get(preview_url(quiz)))
    plain = make_quiz(slug="bez", locales=("en",))
    add_question(plain)
    assert "timed=1" not in text(logged_in.get(preview_url(plain)))


def test_timed_preview_shows_a_countdown_without_polling(frozen, logged_in, monkeypatch):
    html = text(logged_in.get(preview_url(limited_quiz()) + "?timed=1"))
    assert 'data-remaining="600"' in html
    assert "data-time-url" not in html


def test_a_timed_preview_can_switch_it_off(logged_in):
    html = text(logged_in.get(preview_url(limited_quiz()) + "?timed=1"))
    assert "timed=1" not in html.split("mode-bar")[1].split("</p>")[0]


def test_a_timed_preview_over_the_limit_is_refused(frozen, logged_in, monkeypatch):
    quiz = limited_quiz()
    html = text(logged_in.get(preview_url(quiz) + "?timed=1&lang=en"))
    before = row_counts()
    freeze(monkeypatch, TIMED_NOW + timedelta(seconds=601))
    response = submit(logged_in, quiz, html)
    assert response.status_code == 410
    assert "run out" in text(response)
    assert row_counts() == before


def test_a_timed_preview_within_the_limit_is_scored(frozen, logged_in, monkeypatch):
    quiz = limited_quiz()
    html = text(logged_in.get(preview_url(quiz) + "?timed=1"))
    freeze(monkeypatch, TIMED_NOW + timedelta(seconds=600, milliseconds=900))
    assert submit(logged_in, quiz, html).status_code == 200


def test_an_untimed_preview_never_runs_out(frozen, logged_in, monkeypatch):
    quiz = limited_quiz()
    html = text(logged_in.get(preview_url(quiz)))
    freeze(monkeypatch, TIMED_NOW + timedelta(hours=5))
    assert submit(logged_in, quiz, html).status_code == 200


def test_reloading_starts_with_the_full_limit(frozen, logged_in, monkeypatch):
    quiz = limited_quiz()
    logged_in.get(preview_url(quiz) + "?timed=1")
    freeze(monkeypatch, TIMED_NOW + timedelta(minutes=5))
    assert 'data-remaining="600"' in text(logged_in.get(preview_url(quiz) + "?timed=1"))


def test_a_timed_preview_auto_submit_treats_an_unreadable_answer_as_unanswered(logged_in):
    quiz = make_quiz(locales=("en",))
    authoring.save_question(
        quiz,
        None,
        "number",
        {
            "prompt": {"en": "How many?"},
            "value": "10",
            "tolerance": "0",
            "tolerance_kind": "absolute",
        },
    )
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "10", admin_id=None)
    html = text(logged_in.get(preview_url(quiz) + "?timed=1"))
    question = html.split('data-question="')[1].split('"')[0]
    answers = {f"{question}:value": "abc"}
    assert submit(logged_in, quiz, html, answers).status_code == 400
    response = submit(logged_in, quiz, html, answers | {"auto_submit": "1"})
    assert response.status_code == 200
    assert "The time ran out" in text(response) or "Čas vypršel" in text(response)


@pytest.mark.parametrize("when", ["end", "start"])
def test_preview_shows_fields_and_stores_nothing(logged_in, when):
    quiz = published_quiz(locales=("cs", "en"))
    settings.set_override("ask_name", quiz, "required", admin_id=ADMIN_ID)
    settings.set_override("ask_email", quiz, "optional", admin_id=ADMIN_ID)
    settings.set_override("ask_when", quiz, when, admin_id=ADMIN_ID)
    before = row_counts()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert 'name="participant_name"' in html
    assert 'name="participant_email"' in html
    assert 'type="hidden" name="participant_name"' not in html
    result = submit(
        logged_in,
        quiz,
        html,
        {"participant_name": "Tajnajana", "participant_email": "tajne@x.cz"},
    )
    assert result.status_code == 200
    assert "Your score" in text(result)
    assert "Tajnajana" not in text(result)
    assert row_counts() == before
    assert not Participant.objects.exists()


def test_preview_without_name_or_email_shows_no_fields(logged_in):
    quiz = published_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert "participant_name" not in html


def test_preview_steps_by_the_quiz_page_size(logged_in):
    """AC-88: the preview shows the pages a participant will get."""
    quiz = published_quiz(locales=("cs", "en"), questions=3)
    settings.set_override(settings.NAVIGATION_MODE, quiz, "pages", admin_id=ADMIN_ID)
    settings.set_override(settings.PAGE_SIZE, quiz, "2", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    assert 'data-flow-page="2"' in html
