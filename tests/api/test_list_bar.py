"""Managing a list (import, replace, download) sits in one bar above the list (AC-170)."""

import re
from pathlib import Path

import pytest

from tests.domain.helpers import add_question, bank_with, make_quiz

pytestmark = pytest.mark.django_db
TEMPLATES = Path(__file__).resolve().parents[2] / "app"
MANAGING = re.compile(r"url\('admin_import_new'\)|url\('admin_\w+_export'")


def bar_of(html: str) -> str:
    match = re.search(r'<div class="list-bar">.*?list-bar-actions.*?</div>\s*</div>', html, re.S)
    assert match, "no list bar"
    return match.group(0)


def test_quiz_questions_have_a_bar_with_count_and_buttons(logged_in):
    """AC-170: the bar names the list with its count and holds import and download as buttons."""
    quiz = make_quiz()
    add_question(quiz)
    html = logged_in.get(f"/admin/quizzes/{quiz.id}/edit?lang=en").content.decode()
    bar = bar_of(html)
    assert "Questions" in bar and "(1)" in bar
    assert re.search(r'<a href="/admin/import/new\?target=draft:[^"]+" role="button"', bar)
    assert re.search(rf'<a href="/admin/quizzes/{quiz.id}/export" role="button"', bar)
    assert html.index('class="list-bar"') < html.index('<ol class="rows">')


def test_bank_has_the_same_bar(logged_in):
    bank = bank_with(3)
    html = logged_in.get(f"/admin/banks/{bank.id}?lang=en").content.decode()
    bar = bar_of(html)
    assert "Questions" in bar and "(3)" in bar
    assert "target=bank:" in bar and "target=bank_replace:" in bar
    assert f"/admin/banks/{bank.id}/export" in bar


def test_managing_links_live_only_in_a_list_bar_or_a_page_title():
    """A template that links to an import or a download puts the link in `list_bar`."""
    offenders = []
    for path in TEMPLATES.rglob("jinja2/**/*.html"):
        source = path.read_text()
        for match in MANAGING.finditer(source):
            before = source[: match.start()]
            in_bar = before.rfind("{% call list_bar") > before.rfind("{% endcall %}")
            in_title = before.rfind('<div class="page-title">') > before.rfind("</div>")
            in_action = before.endswith('action="{{ ')  # the upload form posts there
            if not (in_bar or in_title or in_action):
                offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, offenders


def test_no_loose_paragraph_of_actions_remains():
    sources = [path.read_text() for path in TEMPLATES.rglob("jinja2/**/*.html")]
    assert not [s for s in sources if '<p class="row-actions">' in s]
