"""AC-86: the "Basic / All" switch and the setting groups on the settings pages."""

import re

import pytest

from app.api import admin_view
from app.api.admin_forms import GlobalSettingsForm
from app.domain import settings
from tests.domain.helpers import make_quiz

pytestmark = pytest.mark.django_db
GROUPS = ["playing", "answers", "participants", "scoreboard", "data", "look", "technical"]


def text(response):
    return response.content.decode()


def test_switch_sets_the_cookie_without_javascript(logged_in):
    response = logged_in.post("/admin/view", {"mode": "all", "next": "/admin/settings"})
    assert response.status_code == 302
    assert response["Location"] == "/admin/settings"
    assert response.cookies[admin_view.COOKIE].value == "all"


def test_switch_refuses_a_foreign_next(logged_in):
    response = logged_in.post("/admin/view", {"mode": "all", "next": "https://evil.example/"})
    assert response["Location"] == "/admin/"


def test_switch_ignores_an_unknown_mode(logged_in):
    response = logged_in.post("/admin/view", {"mode": "expert", "next": "/admin/"})
    assert response.cookies[admin_view.COOKIE].value == "basic"


def test_switch_needs_a_login(client):
    response = client.post("/admin/view", {"mode": "all"})
    assert response.status_code == 302
    assert admin_view.COOKIE not in response.cookies


def test_bar_shows_the_switch_with_the_current_view(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'action="/admin/view"' in html
    assert re.search(r'value="basic"[^>]*aria-pressed="true"', html)
    logged_in.cookies[admin_view.COOKIE] = "all"
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert re.search(r'value="all"[^>]*aria-pressed="true"', html)


def test_global_page_lists_groups_in_order(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert re.findall(r'id="group-(\w+)"', html) == GROUPS
    assert all(f'href="#group-{key}"' in html for key in GROUPS)


def test_basic_hides_advanced_and_counts_them(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'name="navigation_mode"' in html
    assert 'name="shuffle_options"' not in html
    assert re.search(r"More settings in All: \d", html)


def test_all_shows_everything(logged_in):
    logged_in.cookies[admin_view.COOKIE] = "all"
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'name="shuffle_options"' in html
    assert not re.search(r"More settings in All: \d", html)


def test_changed_global_value_shows_in_basic(logged_in):
    settings.set_global(settings.SHUFFLE_OPTIONS, "on", admin_id=None)
    assert 'name="shuffle_options"' in text(logged_in.get("/admin/settings"))


def test_overridden_advanced_setting_shows_in_basic(logged_in):
    """Review Focus 1: an admin always sees why a quiz behaves differently."""
    quiz = make_quiz()
    settings.set_override(settings.SHUFFLE_OPTIONS, quiz, "on", admin_id=None)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert 'name="shuffle_options"' in html
    assert 'name="reveal_level"' not in html


def test_quiz_page_groups_its_settings(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings?lang=en"))
    found = re.findall(r'id="group-(\w+)"', html)
    assert found == [key for key in GROUPS if key in found]  # the global order, none missing
    assert found[:3] == ["playing", "answers", "participants"]


def test_anonymous_label_sits_in_the_scoreboard_group_when_set(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert 'name="anonymous_label_cs"' not in html  # advanced and empty
    quiz.anonymous_label = {"cs": "Tým NN"}
    quiz.save()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    board = html[html.index('id="group-scoreboard"') :]
    assert 'name="anonymous_label_cs"' in board


def test_refused_hidden_field_is_shown_with_its_error(logged_in):
    """Review Focus 2: a refusal on an advanced field is never hidden."""
    settings.set_global(settings.DATA_PROFILE, "score", admin_id=None)
    response = logged_in.post("/admin/settings?lang=en", {settings.ANSWERS_VISIBILITY: "public"})
    html = text(response)
    assert response.status_code == 200
    assert 'name="answers_visibility"' in html
    assert 'class="errorlist' in html


def test_saving_in_basic_keeps_hidden_values(logged_in):
    settings.set_global(settings.REVEAL_LEVEL, "explanations", admin_id=None)
    logged_in.post("/admin/settings", {settings.NAVIGATION_MODE: "step_no_back"})
    assert settings.resolve(settings.REVEAL_LEVEL) == "explanations"
    assert settings.resolve(settings.NAVIGATION_MODE) == "step_no_back"


def test_saving_a_quiz_in_basic_keeps_a_shown_override(logged_in):
    quiz = make_quiz()
    settings.set_override(settings.SHUFFLE_OPTIONS, quiz, "on", admin_id=None)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    chosen = re.search(r'name="shuffle_options"[^>]*>.*?<option value="on" selected', html, re.S)
    assert chosen
    logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings", {"slug": quiz.slug, settings.SHUFFLE_OPTIONS: "on"}
    )
    assert settings.quiz_override(settings.SHUFFLE_OPTIONS, quiz) == "on"


def test_missing_module_settings_do_not_break_grouping():
    """Review Focus 5: a field without a catalogue entry or an extra is left to the page."""
    form = GlobalSettingsForm()
    form.fields["gone_setting"] = form.fields[settings.NAVIGATION_MODE]
    groups = admin_view.group_fields(form, basic=False, differs=lambda name: False)
    names = [field.name for group in groups for field in group.fields]
    assert "gone_setting" not in names and settings.NAVIGATION_MODE in names


def test_switch_on_a_page_drawn_by_a_post_returns_to_a_page(logged_in):
    """A page drawn by a POST-only address must not send the switch back there (405)."""
    from app.domain import authoring
    from tests.domain.helpers import ADMIN_ID, published_quiz

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    response = logged_in.post(f"/admin/runs/{run.id}/code", {"action": "set", "access_code": ""})
    assert response.status_code == 200
    target = re.search(r'name="next" value="([^"]*)"', text(response)).group(1)
    assert logged_in.get(target or "/admin/").status_code in (200, 302)  # not 405
