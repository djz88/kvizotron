"""AC-86: the "Basic / All" switch and the setting groups on the settings pages."""

import re

import pytest

from app.api import admin_view
from app.api.admin_forms import GlobalSettingsForm
from app.domain import settings
from tests.domain.helpers import make_quiz, open_quiz_run

pytestmark = pytest.mark.django_db
GROUPS = [
    "playing",
    "answers",
    "participants",
    "scoreboard",
    "rewards",
    "data",
    "look",
    "technical",
]


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


def panel(html):
    return html.split('class="section-panel"')[1].split("</aside>")[0]


def panel_pages(quiz):
    return [
        "/admin/settings?lang=en",
        f"/admin/quizzes/{quiz.id}/settings?lang=en",
        f"/admin/quizzes/{quiz.id}/plan?lang=en",
    ]


def test_panel_holds_the_switch_with_the_current_view(logged_in):
    """AC-100."""
    html = text(logged_in.get("/admin/settings?lang=en"))
    box = panel(html)
    assert 'action="/admin/view"' in box
    assert re.search(r'value="basic"[^>]*aria-pressed="true"', box)
    logged_in.cookies[admin_view.COOKIE] = "all"
    box = panel(text(logged_in.get("/admin/settings?lang=en")))
    assert re.search(r'value="all"[^>]*aria-pressed="true"', box)


def test_top_bar_has_no_switch(logged_in):
    """AC-100."""
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert html.count('action="/admin/view"') == 1
    assert 'action="/admin/view"' not in html.split('class="section-panel"')[0]


def test_each_settings_page_links_every_section_it_has(logged_in):
    """AC-100."""
    for url in panel_pages(make_quiz()):
        html = text(logged_in.get(url))
        box = panel(html)
        targets = re.findall(r'<a href="#([\w-]+)"', box)
        assert targets, url
        for target in targets:
            assert f'id="{target}"' in html, (url, target)
        assert "<script" not in box
        assert "<details" in box  # the floating list


def test_panel_lists_the_branding_and_clock_sections(logged_in):
    box = panel(text(logged_in.get("/admin/settings?lang=en")))
    assert 'href="#branding"' in box and 'href="#clock"' in box


def test_switch_returns_to_the_same_page(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings?lang=en"))
    assert f'name="next" value="/admin/quizzes/{quiz.id}/settings?lang=en"' in panel(html)


# Alphabetical by the group's label in the admin's language (the user's request after AC-168).
GROUPS_EN = [
    "answers",  # Answers and result
    "data",
    "look",  # Look and listing
    "participants",
    "playing",
    "rewards",
    "scoreboard",
    "technical",
]
GROUPS_CS = [
    "data",
    "rewards",  # Odměny
    "answers",  # Odpovědi a výsledek
    "playing",  # Průchod
    "technical",  # Technické
    "participants",  # Účastníci
    "look",  # Vzhled a výpis
    "scoreboard",  # Žebříček
]


def test_global_page_lists_groups_alphabetically(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert re.findall(r'id="group-(\w+)"', html) == GROUPS_EN
    panel_links = re.findall(r'href="#group-(\w+)"', html)
    assert panel_links == GROUPS_EN
    html = text(logged_in.get("/admin/settings?lang=cs"))
    assert re.findall(r'id="group-(\w+)"', html) == GROUPS_CS


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
    assert found == [key for key in GROUPS_EN if key in found]  # alphabetical, none missing
    assert set(found) == set(GROUPS)


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
    assert "checked" in radio(html, "shuffle_options", "on")  # radios since AC-168
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
    quiz = make_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/plan?lang=en", {"starts_at": "nonsense"})
    assert response.status_code == 200
    target = re.search(r'name="next" value="([^"]*)"', panel(text(response))).group(1)
    assert logged_in.get(target or "/admin/").status_code in (200, 302)  # not 405


def test_run_page_has_the_panel_with_the_switch(logged_in):
    """AC-100: the run page branches on the view, so it offers the switch."""
    run = open_quiz_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    box = panel(html)
    assert 'action="/admin/view"' in box
    assert html.count('action="/admin/view"') == 1
    assert f'name="next" value="/admin/runs/{run.id}?lang=en"' in box
    targets = re.findall(r'<a href="#([\w-]+)"', box)
    assert {"rewards", "scoreboard", "attempts"} <= set(targets)
    for target in targets:
        assert f'id="{target}"' in html, target


def test_run_page_panel_lists_only_sections_shown_in_the_view(logged_in):
    run = open_quiz_run()
    url = f"/admin/runs/{run.id}?lang=en"
    basic = panel(text(logged_in.get(url)))
    assert 'href="#data"' not in basic
    logged_in.cookies[admin_view.COOKIE] = "all"
    html = text(logged_in.get(url))
    assert 'href="#data"' in panel(html) and 'id="data"' in html


def test_the_panel_script_keeps_the_list_open_on_a_wide_screen():
    """AC-100: no JS runner here, so the guard is checked in the source."""
    from pathlib import Path

    source = Path("app/api/assets/sections.js").read_text()
    assert 'list.addEventListener("toggle"' in source
    guard = source.split('list.addEventListener("toggle"')[1].split("});")[0]
    assert "wide.matches" in guard and "list.open = true" in guard


def test_the_panel_script_marks_the_section_whose_top_has_passed_the_upper_third():
    """AC-100: no JS runner here, so the rule is checked in the source."""
    from pathlib import Path

    source = Path("app/api/assets/sections.js").read_text()
    assert "window.innerHeight / 3" in source and "getBoundingClientRect().top <= line" in source
    assert "IntersectionObserver" not in source


# --- the order inside a group (AC-168) -----------------------------------------------------


def _check_order(groups):
    from app.domain.bank_folders import fold

    for group in groups:
        names = [field.name for field in group.fields]
        tops = [f for f in group.fields if f.name not in group.children]

        def key(bound):  # the columns block sorts as its legend
            label = admin_view.COLUMNS_LEGEND if bound.name in admin_view.COLUMNS else bound.label
            return fold(str(label))

        assert [key(f) for f in tops] == sorted(key(f) for f in tops), (
            group.key,
            names,
        )
        for index, name in enumerate(names):
            if name in group.children:
                parent = admin_view.parent_of(name)
                before = names[index - 1]
                assert before == parent or admin_view.parent_of(before) == parent, (name, names)


@pytest.mark.parametrize("language", ["cs", "en"])
def test_a_group_is_alphabetical_with_dependants_under_their_parent(language):
    """AC-168: alphabetical by the translated label, a dependant right under its parent."""
    from django.utils import translation

    with translation.override(language):
        groups = admin_view.group_fields(
            GlobalSettingsForm(), basic=False, differs=lambda name: False
        )
        _check_order(groups)
        playing = next(group for group in groups if group.key == "playing")
        names = [field.name for field in playing.fields]
        assert names[names.index(settings.NAVIGATION_MODE) + 1] == settings.PAGE_SIZE
        assert settings.PAGE_SIZE in playing.children


def test_the_order_follows_the_language():
    from django.utils import translation

    def order(language):
        with translation.override(language):
            groups = admin_view.group_fields(
                GlobalSettingsForm(), basic=False, differs=lambda name: False
            )
        return [field.name for group in groups for field in group.fields]

    assert order("cs") != order("en")
    assert sorted(order("cs")) == sorted(order("en"))


def test_a_dependant_without_its_parent_is_sorted_normally():
    form = GlobalSettingsForm()
    del form.fields[settings.NAVIGATION_MODE]
    groups = admin_view.group_fields(form, basic=False, differs=lambda name: False)
    playing = next(group for group in groups if group.key == "playing")
    assert settings.PAGE_SIZE not in playing.children
    _check_order(groups)


def test_a_dependant_row_is_indented(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    row = re.search(
        r'<div class="([^"]*)"[^>]*>(?:(?!<div class="setting-row).)*?name="page_size"', html, re.S
    )
    assert row and "setting-child" in row.group(1)
    row = re.search(
        r'<div class="([^"]*)"[^>]*>(?:(?!<div class="setting-row).)*?name="navigation_mode"',
        html,
        re.S,
    )
    assert row and "setting-row" in row.group(1) and "setting-child" not in row.group(1)


@pytest.mark.parametrize("name", ["max_attempts", "after_pass"])
def test_the_attempt_limit_rows_are_indented(showing_all, name):
    html = text(showing_all.get("/admin/settings?lang=en"))
    row = re.search(
        rf'<div class="([^"]*)"[^>]*>(?:(?!<div class="setting-row).)*?name="{name}"', html, re.S
    )
    assert row and "setting-child" in row.group(1)


# --- compact rows: radios for short choices, the scoreboard columns together (AC-168) -------


def radio(html, name, value):
    found = re.search(rf'<input type="radio" name="{name}" value="{value}"[^>]*>', html)
    assert found, (name, value)
    return found.group(0)


def test_short_choices_are_radios(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert 'type="radio" name="shuffle_questions"' in html
    assert "checked" in radio(html, "shuffle_questions", settings.resolve("shuffle_questions"))
    assert re.search(r'<select name="navigation_mode"', html)
    assert 'type="radio" name="navigation_mode"' not in html


def test_quiz_page_radio_follows_global_when_not_overridden(showing_all):
    quiz = make_quiz()
    html = text(showing_all.get(f"/admin/quizzes/{quiz.id}/settings?lang=en"))
    assert "checked" in radio(html, "shuffle_questions", "")
    assert "checked" not in radio(html, "shuffle_questions", "on")


def test_choosing_use_global_removes_the_override(showing_all):
    quiz = make_quiz()
    settings.set_override(settings.SHUFFLE_QUESTIONS, quiz, "on", admin_id=None)
    html = text(showing_all.get(f"/admin/quizzes/{quiz.id}/settings?lang=en"))
    assert "checked" in radio(html, "shuffle_questions", "on")
    showing_all.post(
        f"/admin/quizzes/{quiz.id}/settings", {"slug": quiz.slug, settings.SHUFFLE_QUESTIONS: ""}
    )
    assert settings.quiz_override(settings.SHUFFLE_QUESTIONS, quiz) is None


def test_a_refused_save_keeps_the_chosen_radio(showing_all):
    response = showing_all.post(
        "/admin/settings?lang=en",
        {
            settings.NAVIGATION_MODE: "all_at_once",
            settings.REVEAL_MOMENT: "after_each",
            settings.SHUFFLE_QUESTIONS: "on",
        },
    )
    assert response.status_code == 200
    html = text(response)
    assert re.search(r'<option value="after_each" selected>', html)  # four choices: a select
    assert "checked" in radio(html, "shuffle_questions", "on")


def test_a_radio_group_is_named_by_its_label(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    # radiogroup, not group: Pico draws every [role=group] as an inline button bar
    group = re.search(
        r'<div class="setting-row[^"]*" role="radiogroup" aria-labelledby="([^"]+)"', html
    )
    assert group
    assert 'role="group"' not in html.split('settings-form"')[1].split("</form>")[0]
    assert f'id="{group.group(1)}"' in html


def test_columns_are_one_block(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    block = re.search(r'<fieldset class="setting-columns">(.*?)</fieldset>', html, re.S)
    assert block
    assert "<legend>Scoreboard columns</legend>" in block.group(1)
    for name in admin_view.COLUMNS:
        assert f'name="{name}"' in block.group(1)
    assert ">Score<" in block.group(1) and ">Duration<" in block.group(1)
    assert "Column: score" not in block.group(1)


def test_the_settings_form_is_wider(showing_all):
    quiz = make_quiz()
    for address in ("/admin/settings", f"/admin/quizzes/{quiz.id}/settings"):
        assert "settings-form" in text(showing_all.get(address))


def test_labels_have_no_colon_like_the_radio_groups(showing_all):
    html = text(showing_all.get("/admin/settings?lang=en"))
    assert "Questions per page:</label>" not in html
    assert "Questions per page</label>" in html


# --- Time and "Name, logo and texts" look like the groups ------------------------------------


def section(html, section_id):
    found = re.search(rf'<section class="([^"]*)" id="{section_id}"(.*?)</section>', html, re.S)
    assert found, section_id
    return found.group(1), found.group(2)


def test_time_and_branding_sections_are_as_wide_and_drawn_as_the_groups(logged_in):
    quiz = make_quiz()
    for address in ("/admin/settings?lang=en", f"/admin/quizzes/{quiz.id}/settings?lang=en"):
        html = text(logged_in.get(address))
        classes, body = section(html, "branding")
        assert "settings-form" in classes, address
        assert re.search(
            r'<div class="setting-row"[^>]*>\s*<div class="setting-label">'
            r"<label[^>]*>Name in the top bar \(cs\)</label>",
            body,
        )
    classes, body = section(text(logged_in.get("/admin/settings?lang=en")), "clock")
    assert "settings-form" in classes
    assert re.search(r'<div class="setting-label">Server</div>', body)
    assert re.search(r'<div class="setting-label"><label[^>]*>Time zone</label>', body)
