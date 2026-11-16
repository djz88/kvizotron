"""AC-168: the settings pages can be searched like the bank, and a save from the search keeps
every value, also a quiz override of a setting the search hides."""

import re
from html.parser import HTMLParser

import pytest

from app.domain import settings
from tests.domain.helpers import make_quiz

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def row_of(html, name):
    """The opening tag of the row that holds the field `name`."""
    found = re.search(
        rf'(<div class="setting-row[^"]*"[^>]*>)(?:(?!<div class="setting-row).)*?name="{name}"',
        html,
        re.S,
    )
    assert found, name
    return found.group(1)


def group_of(html, key):
    found = re.search(rf'<(?:section|details) class="setting-group" id="group-{key}"[^>]*>', html)
    assert found, key
    return found.group(0)


def test_the_search_form_looks_like_the_bank(logged_in):
    quiz = make_quiz()
    for address in ("/admin/settings?lang=en", f"/admin/quizzes/{quiz.id}/settings?lang=en"):
        html = text(logged_in.get(address))
        form = re.search(
            r'<form method="get" action="[^"]*" class="bank-search" role="search">(.*?)</form>',
            html,
            re.S,
        )
        assert form, address
        assert 'type="search" name="q"' in form.group(1)
        assert ">Search</button>" in form.group(1)


def test_search_shows_matching_settings_and_hides_the_rest(logged_in):
    """AC-168: case and Czech diacritics do not matter."""
    html = text(logged_in.get("/admin/settings?q=ZEBRICEK"))
    assert " hidden" not in row_of(html, "scoreboard_visibility")
    assert " hidden" in row_of(html, "navigation_mode")
    assert " hidden" in group_of(html, "playing")
    assert " hidden" not in group_of(html, "scoreboard")
    panel = html.split('class="section-panel"')[1].split("</aside>")[0]
    assert "#group-scoreboard" in panel and "#group-playing" not in panel


def test_search_finds_an_advanced_setting_in_basic_view(logged_in):
    assert settings.CATALOGUE["tie_break_policy"].level == "advanced"
    html = text(logged_in.get("/admin/settings?lang=en&q=remaining+ties"))
    assert " hidden" not in row_of(html, "tie_break_policy")
    settings_part = html.split('id="branding"')[0]  # the branding texts are not searched
    assert "More settings in All" not in settings_part


def test_search_matches_help_and_value_labels(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en&q=one+person+is+one+row"))  # help text
    assert " hidden" not in row_of(html, "scoreboard_visibility")
    assert " hidden" in row_of(html, "navigation_mode")
    html = text(logged_in.get("/admin/settings?lang=en&q=Visible+after+the+run+ends"))  # a value
    assert " hidden" not in row_of(html, "scoreboard_visibility")
    assert " hidden" in row_of(html, "navigation_mode")


def test_nothing_found_says_so(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en&q=xyzxyz"))
    assert "No setting matches." in html
    assert '<a href="/admin/settings">Clear the search</a>' in html


def test_no_search_shows_no_message(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert "No setting matches." not in html and "Clear the search" not in html


class _Fields(HTMLParser):
    """What a browser would send from one form: checked radios, selected options, values."""

    def __init__(self, action):
        super().__init__()
        self.action, self.inside, self.data, self.select = action, False, {}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            target = a.get("action", "")
            self.inside = target.split("?")[0] == self.action and a.get("method") == "post"
            if self.inside:
                self.target = target
        if not self.inside or "name" not in a and tag != "option":
            return
        if tag == "input":
            kind = a.get("type", "text")
            if kind in ("radio", "checkbox"):
                if "checked" in a:
                    self.data[a["name"]] = a.get("value", "on")
            elif kind not in ("submit", "file"):
                self.data[a["name"]] = a.get("value") or ""
        elif tag == "select":
            self.select = a["name"]
        elif tag == "option" and self.select and "selected" in a:
            self.data[self.select] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "select":
            self.select = None
        if tag == "form":
            self.inside = False


def test_saving_from_the_search_view_keeps_hidden_overrides(logged_in):
    """AC-168: a setting the search hides is still sent, so its quiz override stays."""
    quiz = make_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=None)
    settings.set_override(settings.SHUFFLE_QUESTIONS, quiz, "on", admin_id=None)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings?q=zebricek"))
    assert " hidden" in row_of(html, settings.REVEAL_MOMENT)
    action = f"/admin/quizzes/{quiz.id}/settings"
    parser = _Fields(action)
    parser.feed(html)
    assert parser.data[settings.REVEAL_MOMENT] == "at_end"
    assert parser.target == f"{action}?q=zebricek"
    response = logged_in.post(parser.target, parser.data)
    assert response.status_code == 302
    assert settings.quiz_override(settings.REVEAL_MOMENT, quiz) == "at_end"
    assert settings.quiz_override(settings.SHUFFLE_QUESTIONS, quiz) == "on"


# --- after a refused save (final review) ---------------------------------------------------


def test_the_search_form_goes_to_its_own_page(logged_in):
    """A page drawn by another form's refused POST must not search at that form's address."""
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert re.search(
        rf'<form method="get" action="/admin/quizzes/{quiz.id}/settings" class="bank-search"', html
    )
    html = text(logged_in.get("/admin/settings"))
    assert '<form method="get" action="/admin/settings" class="bank-search"' in html


def test_the_quiz_form_keeps_the_search_through_a_save(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings?q=doba"))
    assert f'action="/admin/quizzes/{quiz.id}/settings?q=doba"' in html


def test_a_refused_save_keeps_a_changed_advanced_setting_in_basic(logged_in):
    """An advanced change without an override yet must stay on the page, or the next save
    drops it silently."""
    quiz = make_quiz()
    assert settings.CATALOGUE[settings.SHUFFLE_OPTIONS].level == "advanced"
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings",
        {
            "slug": quiz.slug,
            settings.NAVIGATION_MODE: "all_at_once",
            settings.REVEAL_MOMENT: "after_each",
            settings.SHUFFLE_OPTIONS: "on",
        },
    )
    assert response.status_code == 200
    html = text(response)
    assert re.search(r'<input type="radio" name="shuffle_options" value="on"[^>]*checked', html)


def test_a_choice_points_to_its_error(logged_in):
    response = logged_in.post(
        "/admin/settings",
        {settings.NAVIGATION_MODE: "all_at_once", settings.REVEAL_MOMENT: "after_each"},
    )
    html = text(response)
    control = re.search(r'<select name="reveal_moment"[^>]*>', html)  # four choices: a select
    assert control and 'aria-describedby="id_reveal_moment_error"' in control.group(0)
    assert 'id="id_reveal_moment_error"' in html
