"""What a request may look like, and which routes are protected by what (TD-009, security.md)."""

import re
from pathlib import Path
from uuid import uuid7

import pytest
from django.test import Client
from django.urls import get_resolver, reverse

import app.api
from app.api import admin_urls
from app.domain.models import Attempt
from tests.domain.helpers import make_quiz, open_quiz_run
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
TEMPLATES = Path(app.api.__file__).parent / "jinja2"
BAD_CHARSET = "multipart/form-data; boundary=x; charset=nonsense"
ARGUMENTS = {
    "link_id": uuid7(),
    "answer_id": uuid7(),
    "job_id": uuid7(),
    "quiz_id": uuid7(),
    "run_id": uuid7(),
    "question_id": uuid7(),
    "revision_no": 1,
    "bank_id": uuid7(),
    "draw_id": "x",
    "rule_id": uuid7(),
    "entitlement_id": uuid7(),
}


def test_multipart_is_refused_on_public_start():
    run = open_quiz_run()
    response = Client().post(f"/r/{run.id}/start", {"lang": "cs"})
    assert response.status_code == 415
    assert not Attempt.objects.exists()


def test_multipart_with_invalid_charset_is_not_a_server_error():
    response = Client().generic("POST", "/admin/login", b"x", content_type=BAD_CHARSET)
    assert response.status_code == 415


def test_form_still_works():
    run = open_quiz_run()
    assert FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}).status_code == 200


def test_get_is_not_affected():
    assert Client().get("/", content_type=BAD_CHARSET).status_code == 200


def test_only_play_routes_are_csrf_exempt():
    exempt = {
        pattern.name
        for pattern in get_resolver().url_patterns
        if getattr(getattr(pattern, "callback", None), "csrf_exempt", False)
    }
    assert exempt == {"start", "resume", "submit", "switch", "check", "attempt_time"}


@pytest.mark.parametrize("pattern", admin_urls.urlpatterns, ids=lambda p: p.name)
def test_every_admin_route_refuses_post_without_csrf_token(admin_user, pattern):
    names = pattern.pattern.converters
    client = FormClient(enforce_csrf_checks=True)
    client.force_login(admin_user)
    url = reverse(pattern.name, kwargs={name: ARGUMENTS[name] for name in names})
    assert client.post(url).status_code == 403


@pytest.mark.parametrize(
    "template", sorted((TEMPLATES / "admin").glob("*.html")), ids=lambda path: path.name
)
def test_every_admin_form_carries_a_csrf_token(template):
    html = template.read_text()
    assert len(re.findall(r'method="post"', html)) == html.count("{{ csrf_input }}")


def multipart(client, path):
    return client.post(path, {"prompt_cs": "Q"})  # plain Client sends multipart


def test_multipart_allowed_only_on_question_editor_routes(admin_user):
    quiz = make_quiz()
    client = Client()
    client.force_login(admin_user)
    new = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    assert multipart(client, new).status_code == 302  # the view saved the question
    edit = f"/admin/quizzes/{quiz.id}/questions/abc/edit"
    assert multipart(client, edit).status_code == 404  # reached the view
    for refused in (
        f"/admin/quizzes/{quiz.id}/edit",
        f"/admin/quizzes/{quiz.id}/questions/abc/delete",
        f"/admin/quizzes/{quiz.id}/questions/new/extra",
        "/admin/settings",
        "/",
    ):
        assert multipart(client, refused).status_code == 415, refused


def test_anonymous_multipart_to_the_editor_gets_no_upload():
    quiz = make_quiz()
    response = multipart(Client(), f"/admin/quizzes/{quiz.id}/questions/new?type=choice")
    assert response.status_code == 415


def test_multipart_with_invalid_charset_to_the_editor_is_not_a_server_error(admin_user):
    quiz = make_quiz()
    client = Client()
    client.force_login(admin_user)
    response = client.generic(
        "POST",
        f"/admin/quizzes/{quiz.id}/questions/new?type=choice",
        b"x",
        content_type="multipart/form-data; boundary=x; charset=nonsense",
    )
    assert response.status_code == 415
