import pytest

from app.domain import settings
from app.domain.models import AppSetting, QuizRevision
from tests.domain.helpers import make_quiz, published_quiz

pytestmark = pytest.mark.django_db
KEY = settings.REVISION_SWITCH_POLICY


def test_settings_page_requires_login(client):
    assert client.get("/admin/settings").status_code == 302


def test_global_setting_is_saved_and_shown(logged_in):
    response = logged_in.post("/admin/settings", {KEY: "let_finish"})
    assert response.status_code == 302
    assert settings.resolve(KEY) == "let_finish"
    page = logged_in.get("/admin/settings").content.decode()
    assert 'value="let_finish" selected' in page


def test_invalid_posted_value_shows_form_error_and_stores_nothing(logged_in):
    response = logged_in.post("/admin/settings", {KEY: "nope"})
    assert response.status_code == 200
    assert not AppSetting.objects.exists()


def test_nav_links_to_settings(logged_in):
    assert 'href="/admin/settings"' in logged_in.get("/admin/quizzes").content.decode()


def test_quiz_override_form_saves_and_clears(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings"
    assert logged_in.post(url, {"slug": quiz.slug, KEY: "notify_switch"}).status_code == 302
    assert settings.quiz_override(KEY, quiz) == "notify_switch"
    assert logged_in.post(url, {"slug": quiz.slug, KEY: ""}).status_code == 302
    assert settings.quiz_override(KEY, quiz) is None


def test_quiz_override_invalid_value_stores_nothing(logged_in):
    quiz = make_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings"
    response = logged_in.post(url, {"slug": quiz.slug, KEY: "nope"})
    assert response.status_code == 200
    assert settings.quiz_override(KEY, quiz) is None


def test_quiz_override_requires_login(client):
    quiz = make_quiz()
    client.post(f"/admin/quizzes/{quiz.id}/settings", {KEY: "let_finish"})
    assert settings.quiz_override(KEY, quiz) is None


def test_settings_tab_names_current_global_value(logged_in):
    settings.set_global(KEY, "let_finish", admin_id=None)
    page = logged_in.get(f"/admin/quizzes/{make_quiz().id}/settings?lang=en").content.decode()
    assert "Use global setting (now: Let participants finish" in page


def test_quiz_override_does_not_create_a_draft(logged_in):
    quiz = published_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings"
    logged_in.post(url, {"slug": quiz.slug, KEY: "let_finish"})
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_global_form_refuses_after_each_with_all_at_once(logged_in):
    response = logged_in.post(
        "/admin/settings",
        {settings.NAVIGATION_MODE: "all_at_once", settings.REVEAL_MOMENT: "after_each"},
    )
    assert response.status_code == 200
    assert "režim po jedné" in response.content.decode()
    assert settings.resolve(settings.REVEAL_MOMENT) == "never"


def test_quiz_form_refuses_conflict_of_effective_values(logged_in):
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        {"slug": quiz.slug, settings.REVEAL_MOMENT: "after_each"},
    )
    assert response.status_code == 200
    assert "režim po jedné" in response.content.decode()
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) is None


def test_quiz_form_accepts_after_each_with_its_own_step_mode(logged_in):
    quiz = make_quiz()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        {
            "slug": quiz.slug,
            settings.REVEAL_MOMENT: "after_each",
            settings.NAVIGATION_MODE: "step_back",
        },
    )
    assert response.status_code == 302
    assert settings.flow(quiz).moment == "after_each"


def test_quiz_settings_warn_on_fallback(logged_in):
    quiz = make_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    page = logged_in.get(f"/admin/quizzes/{quiz.id}/settings").content.decode()
    assert 'class="notice' in page
    assert "na konci" in page
