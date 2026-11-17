"""AC-18, AC-81: forms refuse a scoreboard that cannot go with the run's other settings."""

from datetime import UTC, datetime

import pytest

from app.contracts import SCOREBOARD_VISIBILITY
from app.domain import authoring, results, settings
from tests.domain.helpers import ADMIN_ID, make_quiz, published_quiz
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
START = "2030-01-01T18:00"


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def plan(client, quiz, **fields):
    data = {"starts_at": START, "deadline_at": "", "limit_minutes": ""} | fields
    return client.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", data)


def answers_after_each(quiz):
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_back", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=ADMIN_ID)


def test_plan_form_sets_visibility(logged_in):
    quiz = published_quiz()
    plan(logged_in, quiz, scoreboard_visibility="after_end")
    assert results.of(quiz.runs.get())[SCOREBOARD_VISIBILITY] == "after_end"


def test_plan_form_says_a_visible_board_adds_a_cookie(logged_in):
    html = text(logged_in.get(f"/admin/quizzes/{published_quiz().id}/plan?lang=en"))
    assert "cookie, so one person is one row" in html


def test_visible_board_refused_with_profile_none(logged_in):
    quiz = published_quiz()
    response = plan(logged_in, quiz, scoreboard_visibility="live", data_profile="none")
    assert "scoreboard" in text(response).lower()
    assert not quiz.runs.exists()


def test_visible_board_refused_with_answers_after_each(logged_in):
    quiz = published_quiz()
    answers_after_each(quiz)
    response = plan(logged_in, quiz, scoreboard_visibility="live")
    assert "Answers after each question cannot go with a visible scoreboard." in text(response)
    assert not quiz.runs.exists()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings?lang=en", {SCOREBOARD_VISIBILITY: "live"}
    )
    assert "Answers after each question cannot go with a visible scoreboard." in text(response)
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "hidden"


def test_scoreboard_form_saves_display_values(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    response = logged_in.post(
        f"/admin/runs/{run.id}/scoreboard/settings", {SCOREBOARD_VISIBILITY: "live"}
    )
    assert response.status_code == 302
    run.refresh_from_db()
    assert results.of(run)[SCOREBOARD_VISIBILITY] == "live"


def test_after_each_refused_on_quiz_with_visible_board(logged_in):
    """AC-18: answers after each question are refused, with a reason, beside a visible board."""
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings?lang=en",
        {"slug": quiz.slug, "navigation_mode": "step_back", "reveal_moment": "after_each"},
    )
    assert "Answers after each question cannot go with a visible scoreboard." in text(response)
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None


def test_after_each_refused_with_visible_board_in_the_same_form(logged_in):
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings?lang=en",
        {
            "slug": quiz.slug,
            "navigation_mode": "step_back",
            "reveal_moment": "after_each",
            SCOREBOARD_VISIBILITY: "live",
        },
    )
    assert "Answers after each question cannot go with a visible scoreboard." in text(response)


def test_duration_column_needs_detailed(logged_in):
    quiz = published_quiz()
    response = plan(logged_in, quiz, scoreboard_show_duration="on", data_profile="answers")
    assert not quiz.runs.exists()
    assert "times" in text(response)
    plan(logged_in, quiz, scoreboard_show_duration="on", data_profile="detailed")
    assert quiz.runs.exists()


def test_label_saved_per_language(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        {"slug": quiz.slug, "anonymous_label_cs": "<b>Tým</b> NN", "anonymous_label_en": ""},
    )
    assert response.status_code == 302
    quiz.refresh_from_db()
    assert quiz.anonymous_label == {"cs": "<b>Tým</b> NN"}


def test_label_longer_than_40_is_refused(logged_in):
    quiz = make_quiz()
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        {"slug": quiz.slug, "anonymous_label_cs": "x" * 41},
    )
    quiz.refresh_from_db()
    assert quiz.anonymous_label == {}


def test_label_sits_with_the_scoreboard_settings(showing_all):
    logged_in = showing_all
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    behaviour = html[html.index('name="slug"') :]
    assert 'name="anonymous_label_cs"' in behaviour
    assert html.count('name="anonymous_label_cs"') == 1
    assert html.index('name="scoreboard_unnamed"') < html.index('name="anonymous_label_cs"')


def test_label_offered_only_in_the_quiz_languages_and_others_kept(showing_all):
    logged_in = showing_all
    quiz = make_quiz(locales=("cs",))
    quiz.anonymous_label = {"en": "Guest NN"}
    quiz.save()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert 'name="anonymous_label_cs"' in html and 'name="anonymous_label_en"' not in html
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings", {"slug": quiz.slug, "anonymous_label_cs": "Tým NN"}
    )
    quiz.refresh_from_db()
    assert quiz.anonymous_label == {"cs": "Tým NN", "en": "Guest NN"}


def test_saving_title_keeps_the_label(logged_in):
    quiz = make_quiz()
    quiz.anonymous_label = {"cs": "Tým NN"}
    quiz.save()
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/edit",
        {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Nový"},
    )
    quiz.refresh_from_db()
    assert quiz.anonymous_label == {"cs": "Tým NN"}


def test_global_after_each_refused_while_an_inheriting_run_shows_a_board(logged_in):
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    response = logged_in.post(
        "/admin/settings?lang=en", {"navigation_mode": "step_back", "reveal_moment": "after_each"}
    )
    assert "Answers after each question cannot go with a visible scoreboard." in text(response)
    assert settings.resolve(settings.REVEAL_MOMENT) != "after_each"


def test_global_after_each_allowed_when_the_quiz_overrides_it(logged_in):
    quiz = published_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "never", admin_id=ADMIN_ID)
    authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    logged_in.post(
        "/admin/settings?lang=en", {"navigation_mode": "step_back", "reveal_moment": "after_each"}
    )
    assert settings.resolve(settings.REVEAL_MOMENT) == "after_each"
