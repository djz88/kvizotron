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


def test_settings_tab_names_current_global_value(showing_all):
    logged_in = showing_all
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
    settings.set_global(settings.NAVIGATION_MODE, "all_at_once", admin_id=None)
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
    settings.set_global(settings.NAVIGATION_MODE, "all_at_once", admin_id=None)
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    page = logged_in.get(f"/admin/quizzes/{quiz.id}/settings").content.decode()
    assert 'class="notice' in page
    assert "na konci" in page


def test_settings_page_has_the_clock_panel(logged_in):
    html = logged_in.get("/admin/settings").content.decode()
    assert 'id="clock"' in html
    assert "data-server-epoch" in html
    assert 'data-zone="Europe/Prague"' in html
    assert "clock.js" in html


def test_the_time_zone_can_be_chosen(logged_in):
    html = logged_in.get("/admin/settings").content.decode()
    assert '<select name="time_zone"' in html


def test_the_time_panel_comes_first_with_server_browser_and_the_zone_choice(showing_all):
    logged_in = showing_all
    """Server time and zone, browser time and zone, then the app's zone right below."""
    html = logged_in.get("/admin/settings").content.decode()
    panel_start = html.index('id="clock"')
    panel = html[panel_start : html.index("</section>", panel_start)]
    assert "Server" in panel
    assert "data-browser" in panel
    assert '<select name="time_zone"' in panel
    assert html.count('name="time_zone"') == 1
    assert panel_start < html.index('name="revision_switch_policy"')


def test_the_time_zone_is_saved_from_the_panel(logged_in):
    from app.domain import settings as domain_settings

    form = logged_in.get("/admin/settings").content.decode()
    assert "<form" in form[: form.index('id="clock"')]
    data = {key: domain_settings.resolve(key) for key in domain_settings.keys_for("global")}
    data["time_zone"] = "Europe/London"
    logged_in.post("/admin/settings", data)
    assert domain_settings.resolve(domain_settings.TIME_ZONE) == "Europe/London"


def test_the_server_time_carries_what_the_browser_needs_to_show_it_in_its_own_format(logged_in):
    html = logged_in.get("/admin/settings").content.decode()
    panel = html[html.index('id="clock"') :]
    assert "<strong data-server-time>" in panel
    assert 'data-server-zone="' in html
