"""A quiz can name the address its QR code and public link use (another name, a redirect)."""

import re

import segno

from app.domain.models import Quiz
from tests.domain.helpers import make_quiz

NEW = {"supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Evropa", "slug": "evropa"}


def text(response):
    return response.content.decode()


def settings_post(quiz, **fields):
    return {"slug": quiz.slug, "featured": "", **fields}


def test_a_new_quiz_takes_its_public_address(logged_in):
    response = logged_in.post("/admin/quizzes/new", NEW | {"public_origin": "Kviz.Example.cz/"})
    assert response.status_code == 302
    assert Quiz.objects.get(slug="evropa").public_origin == "https://kviz.example.cz"


def test_without_one_the_address_is_the_admins_own(logged_in):
    quiz = make_quiz("evropa")
    svg = logged_in.get(f"/admin/quizzes/{quiz.id}/qr.svg").content
    assert svg == io_svg("http://testserver/q/evropa")
    edit = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert '<a href="/q/evropa">/q/evropa</a>' in edit


def test_the_public_address_drives_the_link_and_the_qr_code(logged_in):
    """AC-179: the QR code, the Runs tab and the header use the quiz's own address."""
    quiz = make_quiz("evropa", public_origin="https://kviz.example.cz:8443")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    assert "https://kviz.example.cz:8443/q/evropa" in html
    edit = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert 'href="https://kviz.example.cz:8443/q/evropa"' in edit
    svg = logged_in.get(f"/admin/quizzes/{quiz.id}/qr.svg").content
    expected = io_svg("https://kviz.example.cz:8443/q/evropa")
    assert svg == expected


def io_svg(address):
    import io

    buffer = io.BytesIO()
    segno.make(address, error="m").save(buffer, kind="svg", scale=4, border=2)
    return buffer.getvalue()


def test_the_settings_change_it_and_refuse_a_path(logged_in):
    quiz = make_quiz("evropa")
    url = f"/admin/quizzes/{quiz.id}/settings?lang=en"
    refused = logged_in.post(url, settings_post(quiz, public_origin="https://kviz.example.cz/q/x"))
    assert refused.status_code == 200
    assert re.search(r"Type only the start of the address", text(refused))
    assert (
        logged_in.post(url, settings_post(quiz, public_origin="192.168.1.10:8443")).status_code
        == 302
    )
    quiz.refresh_from_db()
    assert quiz.public_origin == "https://192.168.1.10:8443"
    assert logged_in.post(url, settings_post(quiz, public_origin="")).status_code == 302
    quiz.refresh_from_db()
    assert quiz.public_origin == ""


def test_both_quiz_forms_show_the_field(logged_in):
    assert 'name="public_origin"' in text(logged_in.get("/admin/quizzes/new"))
    quiz = make_quiz("evropa", public_origin="https://kviz.example.cz")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert 'name="public_origin"' in html and 'value="https://kviz.example.cz"' in html


import pytest  # noqa: E402


@pytest.mark.parametrize(
    ("typed", "saved"),
    [
        ("https://kviz.example.cz/", "https://kviz.example.cz"),
        ("http://kviz.example.cz", "http://kviz.example.cz"),
        ("HTTPS://Kviz.Example.cz:8443", "https://kviz.example.cz:8443"),
        ("https://" + "a" * 191 + ".cz", None),
        ("https://user@kviz.example.cz", None),
        ("ftp://kviz.example.cz", None),
    ],
)
def test_the_address_is_kept_to_its_start(logged_in, typed, saved):
    quiz = make_quiz("evropa")
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/settings", settings_post(quiz, public_origin=typed)
    )
    quiz.refresh_from_db()
    if saved is None:
        assert response.status_code == 200 and quiz.public_origin == ""
    else:
        assert response.status_code == 302 and quiz.public_origin == saved


def test_the_saved_address_reaches_the_run_page(logged_in):
    from tests.domain.helpers import open_quiz_run

    run = open_quiz_run()
    run.quiz.public_origin = "https://kviz.example.cz"
    run.quiz.save()
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert f"https://kviz.example.cz/q/{run.quiz.slug}" in html


def test_each_field_outside_the_groups_has_its_own_row(logged_in):
    """A checkbox is inline: without a row of its own the next field's label joins its line."""
    quiz = make_quiz("evropa")
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert re.search(r'<input type="checkbox" name="featured"[^>]*>\s*</div>', html)
    assert re.search(r'<div>\s*<label for="id_public_origin"', html)
