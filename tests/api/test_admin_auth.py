from uuid import uuid7

import pytest
from django.conf import settings

from tests.api.conftest import PASSWORD
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
ID = uuid7()
ROUTES = [
    "/admin/",
    "/admin/quizzes",
    "/admin/quizzes/new",
    f"/admin/quizzes/{ID}/edit",
    f"/admin/quizzes/{ID}/questions/new",
    f"/admin/quizzes/{ID}/questions/x/edit",
    f"/admin/quizzes/{ID}/questions/x/delete",
    f"/admin/quizzes/{ID}/publish",
    f"/admin/quizzes/{ID}/runs",
    f"/admin/quizzes/{ID}/qr.svg",
    f"/admin/runs/{ID}",
    f"/admin/runs/{ID}/close",
    "/admin/users",
]


def login(client, password=PASSWORD, username="alice", **extra):
    return client.post("/admin/login", {"login": username, "password": password, **extra})


@pytest.mark.parametrize("path", ROUTES)
def test_every_admin_route_redirects_anonymous_get_to_login_and_back(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login?next=")


@pytest.mark.parametrize("path", ROUTES)
def test_expired_session_on_post_goes_to_login_without_next(client, path):
    """Returning there by GET would be a dead end: many of these routes accept only POST."""
    response = client.post(path)
    assert (response.status_code, response["Location"]) == (302, "/admin/login")


def test_login_with_correct_password_opens_quiz_list(client, admin_user):
    response = login(client)
    assert (response.status_code, response["Location"]) == (302, "/admin/quizzes")
    assert client.get("/admin/quizzes").status_code == 200


def test_login_with_wrong_password_shows_same_message_as_unknown_login(client, admin_user):
    wrong = login(client, "spatne-heslo-12345")
    unknown = login(client, username="nobody")
    assert wrong.status_code == unknown.status_code == 200
    assert "Nesprávné přihlašovací jméno nebo heslo." in wrong.content.decode()
    assert "Nesprávné přihlašovací jméno nebo heslo." in unknown.content.decode()
    assert client.get("/admin/quizzes").status_code == 302


def test_login_form_does_not_echo_password(client, admin_user):
    assert "spatne-heslo-12345" not in login(client, "spatne-heslo-12345").content.decode()


def test_inactive_admin_cannot_log_in(client, admin_user):
    admin_user.is_active = False
    admin_user.save()
    assert login(client).status_code == 200
    assert client.get("/admin/quizzes").status_code == 302


@pytest.mark.parametrize(
    "target",
    ["https://evil.example.net/", "//evil.example.net", "javascript:alert(1)", ""],
)
def test_login_next_stays_on_site(client, admin_user, target):
    assert login(client, next=target)["Location"] == "/admin/quizzes"


def test_login_next_local_path_is_followed(client, admin_user):
    page = client.get("/admin/users")
    assert page["Location"] == "/admin/login?next=/admin/users"
    assert 'name="next" value="/admin/users"' in client.get(page["Location"]).content.decode()
    assert login(client, next="/admin/users")["Location"] == "/admin/users"


def test_login_page_redirects_logged_in_admin(logged_in):
    assert logged_in.get("/admin/login")["Location"] == "/admin/quizzes"


def test_login_post_without_csrf_token_is_403(admin_user):
    assert login(FormClient(enforce_csrf_checks=True)).status_code == 403


def test_logout_is_post_only_and_ends_session(logged_in):
    assert logged_in.get("/admin/logout").status_code == 405
    assert logged_in.get("/admin/quizzes").status_code == 200
    assert logged_in.post("/admin/logout")["Location"] == "/admin/login"
    assert logged_in.get("/admin/quizzes").status_code == 302


def test_admin_language_is_chosen_and_kept_in_session(logged_in):
    assert "Quizzes" in logged_in.get("/admin/quizzes?lang=en").content.decode()
    assert "Quizzes" in logged_in.get("/admin/quizzes").content.decode()
    assert "Kvízy" in logged_in.get("/admin/quizzes?lang=cs").content.decode()
    assert "Kvízy" in logged_in.get("/admin/quizzes?lang=uk").content.decode()


def test_admin_offers_only_cs_and_en(logged_in):
    html = logged_in.get("/admin/quizzes").content.decode()
    assert "?lang=en" in html and "?lang=uk" not in html


def test_session_cookie_expires_in_12_hours(client, admin_user):
    login(client)
    assert client.cookies[settings.SESSION_COOKIE_NAME]["max-age"] == 12 * 60 * 60


def test_admin_pages_are_not_cached(logged_in):
    assert "no-store" in logged_in.get("/admin/quizzes")["Cache-Control"]
