import re

import pytest

from app.domain.models import Quiz
from app.kernel.models import AdminUser, AuditEvent
from tests.domain.helpers import make_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
GOOD = "jine-dlouhe-heslo-42"


def create(client, login="bob", password=GOOD):
    return client.post("/admin/users", {"login": login, "password": password})


def test_list_shows_admins(logged_in):
    assert "alice" in logged_in.get("/admin/users").content.decode()


def test_create_second_admin_who_can_log_in(logged_in):
    assert create(logged_in)["Location"] == "/admin/users"
    response = FormClient().post("/admin/login", {"login": "bob", "password": GOOD})
    assert response.status_code == 302


@pytest.mark.parametrize("password", ["kratke", "password123"])
def test_weak_password_is_refused(logged_in, password):
    response = create(logged_in, password=password)
    assert response.status_code == 200
    assert "errorlist" in response.content.decode()
    assert not AdminUser.objects.filter(login="bob").exists()


def test_duplicate_login_is_refused(logged_in):
    response = create(logged_in, login="alice")
    assert "Tento login už existuje." in response.content.decode()
    assert AdminUser.objects.count() == 1


@pytest.mark.parametrize("login", ["", "   ", "x" * 151])
def test_invalid_login_is_refused(logged_in, login):
    assert "errorlist" in create(logged_in, login=login).content.decode()
    assert AdminUser.objects.count() == 1


def test_creating_admin_is_audited_without_password(logged_in, admin_user):
    create(logged_in)
    bob = AdminUser.objects.get(login="bob")
    event = AuditEvent.objects.get(action="admin.created")
    assert (event.actor_type, event.actor_id) == ("admin", str(admin_user.pk))
    assert event.entity_id == str(bob.pk)
    assert GOOD not in str(event.details_json)


def test_password_is_never_echoed_back(logged_in):
    assert "kratke" not in create(logged_in, password="kratke").content.decode()


def test_new_admin_can_have_an_email(logged_in):
    create_with_email = logged_in.post(
        "/admin/users", {"login": "bob", "password": GOOD, "email": "bob@example.org"}
    )
    assert create_with_email["Location"] == "/admin/users"
    assert AdminUser.objects.get(login="bob").email == "bob@example.org"


def test_email_is_optional_and_validated(logged_in):
    create(logged_in)
    assert AdminUser.objects.get(login="bob").email == ""
    bad = logged_in.post("/admin/users", {"login": "eve", "password": GOOD, "email": "nope"})
    assert "errorlist" in bad.content.decode()
    long_mail = "a" * 250 + "@x.cz"
    bad = logged_in.post("/admin/users", {"login": "eve", "password": GOOD, "email": long_mail})
    assert "errorlist" in bad.content.decode()
    assert not AdminUser.objects.filter(login="eve").exists()


def test_email_is_edited_on_the_list_and_audited_without_value(logged_in, admin_user):
    """AC-99."""
    response = logged_in.post(
        "/admin/users", {"admin_id": str(admin_user.pk), "email": "alice@example.org"}
    )
    assert response["Location"] == "/admin/users"
    admin_user.refresh_from_db()
    assert admin_user.email == "alice@example.org"
    event = AuditEvent.objects.get(action="admin.email_changed")
    assert event.entity_id == str(admin_user.pk)
    assert "alice@example.org" not in str(event.details_json)
    logged_in.post("/admin/users", {"admin_id": str(admin_user.pk), "email": ""})
    admin_user.refresh_from_db()
    assert admin_user.email == ""


def test_email_change_of_an_unknown_admin_is_a_404(logged_in):
    response = logged_in.post(
        "/admin/users", {"admin_id": "00000000-0000-7000-8000-0000000000ff", "email": "a@b.org"}
    )
    assert response.status_code == 404
    assert not AuditEvent.objects.filter(action="admin.email_changed").exists()


def test_invalid_email_edit_is_refused(logged_in, admin_user):
    response = logged_in.post("/admin/users", {"admin_id": str(admin_user.pk), "email": "nope"})
    assert response.status_code == 200
    admin_user.refresh_from_db()
    assert admin_user.email == ""


def test_ids_on_the_page_are_unique(logged_in):
    import re

    create(logged_in)
    html = logged_in.get("/admin/users").content.decode()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert 'name="email"' in html and 'name="admin_id"' in html


def test_ids_stay_unique_when_an_email_is_refused(logged_in):
    import re

    create(logged_in)
    pk = AdminUser.objects.get(login="bob").pk
    response = logged_in.post("/admin/users", {"admin_id": str(pk), "email": "nope"})
    html = response.content.decode()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert "errorlist" in html


# --- editing and deleting accounts (AC-169) ---------------------------------


HX = {"HTTP_HX_REQUEST": "true"}
NEW = "nove-dlouhe-heslo-77"


@pytest.fixture
def bob(db):
    return AdminUser.objects.create_admin("bob", GOOD)


@pytest.fixture
def bob_client(bob):
    client = FormClient()
    client.force_login(bob)
    return client


def logged_out(client) -> bool:
    response = client.get("/admin/users")
    return response.status_code == 302 and "/admin/login" in response["Location"]


def url(admin, action=""):
    return f"/admin/admins/{admin.pk}/{action}"


def row_of(html: str, admin) -> str:
    """The card of one admin on the page."""
    match = re.search(rf'<li id="admin-{admin.pk}".*?</li>', html, re.S)
    assert match, f"no card for {admin.login}"
    return match.group(0)


def test_each_account_has_its_actions_and_ones_own_has_no_block_or_delete(
    logged_in, admin_user, bob
):
    html = logged_in.get("/admin/users").content.decode()
    theirs = row_of(html, bob)
    assert url(bob, "login") in theirs  # the pencil
    assert 'name="email"' in theirs
    assert f'action="{url(bob, "password")}"' in theirs
    assert f'action="{url(bob, "active")}"' in theirs
    assert url(bob, "delete") in theirs
    mine = row_of(html, admin_user)
    assert url(admin_user, "login") in mine
    assert f'action="{url(admin_user, "password")}"' in mine
    assert url(admin_user, "active") not in mine
    assert url(admin_user, "delete") not in mine


def test_every_form_on_the_page_has_a_csrf_token(logged_in, bob):
    html = logged_in.get("/admin/users").content.decode()
    forms = re.findall(r"<form\b.*?</form>", html, re.S)
    posting = [form for form in forms if 'method="post"' in form]
    assert len(posting) >= 6
    assert all("csrfmiddlewaretoken" in form for form in posting)


def test_rename_by_htmx_shows_the_new_login(logged_in, bob):
    response = logged_in.post(url(bob, "login"), {"login": "robert"}, **HX)
    assert response.status_code == 200
    assert "robert" in response.content.decode()
    bob.refresh_from_db()
    assert bob.login == "robert"


def test_rename_without_javascript(logged_in, bob):
    opened = logged_in.get(url(bob, "login") + "?edit=1")
    assert opened["Location"] == f"/admin/users?edit=login-{bob.pk}"
    page_html = logged_in.get(opened["Location"]).content.decode()
    assert f'action="{url(bob, "login")}"' in row_of(page_html, bob)
    assert 'name="login" value="bob"' in row_of(page_html, bob)
    saved = logged_in.post(url(bob, "login"), {"login": "robert"})
    assert saved["Location"] == "/admin/users"
    bob.refresh_from_db()
    assert bob.login == "robert"


def test_rename_to_a_taken_login_keeps_the_typed_text(logged_in, bob):
    response = logged_in.post(url(bob, "login"), {"login": "alice"}, **HX)
    assert response.status_code == 400
    html = response.content.decode()
    assert "Tento login už existuje." in html
    assert 'value="alice"' in html
    page_response = logged_in.post(url(bob, "login"), {"login": "alice"})
    assert page_response.status_code == 400
    assert 'name="login" value="alice"' in row_of(page_response.content.decode(), bob)
    bob.refresh_from_db()
    assert bob.login == "bob"


def test_rename_to_an_empty_login_is_refused(logged_in, bob):
    response = logged_in.post(url(bob, "login"), {"login": "  "}, **HX)
    assert response.status_code == 400
    bob.refresh_from_db()
    assert bob.login == "bob"


def test_new_password_for_another_ends_their_session(logged_in, bob, bob_client):
    response = logged_in.post(url(bob, "password"), {"password": NEW})
    assert response["Location"] == "/admin/users"
    assert logged_out(bob_client)
    assert FormClient().post("/admin/login", {"login": "bob", "password": NEW}).status_code == 302
    assert not logged_out(logged_in)


def test_own_new_password_keeps_the_session(logged_in, admin_user):
    response = logged_in.post(url(admin_user, "password"), {"password": NEW})
    assert response["Location"] == "/admin/users"
    assert not logged_out(logged_in)
    admin_user.refresh_from_db()
    assert admin_user.check_password(NEW)


def test_weak_new_password_is_refused_and_not_echoed(logged_in, bob):
    response = logged_in.post(url(bob, "password"), {"password": "kratke"})
    assert response.status_code == 400
    html = response.content.decode()
    assert 'class="notice"' in html
    assert "kratke" not in html
    bob.refresh_from_db()
    assert bob.check_password(GOOD)


def test_blocked_admin_is_logged_out_and_cannot_log_in(logged_in, bob, bob_client):
    response = logged_in.post(url(bob, "active"), {"active": "0"})
    assert response["Location"] == "/admin/users"
    assert logged_out(bob_client)
    login = FormClient().post("/admin/login", {"login": "bob", "password": GOOD})
    assert login.status_code != 302
    assert "Blokovaný" in row_of(logged_in.get("/admin/users").content.decode(), bob)
    logged_in.post(url(bob, "active"), {"active": "1"})
    assert FormClient().post("/admin/login", {"login": "bob", "password": GOOD}).status_code == 302


def test_one_cannot_block_or_delete_oneself(logged_in, admin_user, bob):
    for response in (
        logged_in.post(url(admin_user, "active"), {"active": "0"}),
        logged_in.post(url(admin_user, "delete"), {"confirm": "1"}),
    ):
        assert response.status_code == 409
        assert "Vlastní účet nejde zablokovat ani smazat." in response.content.decode()
    admin_user.refresh_from_db()
    assert admin_user.is_active


def test_last_admin_refusal_is_shown(logged_in, bob, monkeypatch):
    """A logged-in actor is active, so only a race reaches this; the page still says why."""
    from app.domain import admins

    def refuse(*args, **kwargs):
        raise admins.LastAdmin

    monkeypatch.setattr(admins, "set_active", refuse)
    monkeypatch.setattr(admins, "delete", refuse)
    for response in (
        logged_in.post(url(bob, "active"), {"active": "0"}),
        logged_in.post(url(bob, "delete"), {"confirm": "1"}),
    ):
        assert response.status_code == 409
        assert "Musí zůstat aspoň jeden další aktivní správce." in response.content.decode()


def test_delete_asks_first_and_deletes_on_post(logged_in, bob):
    quiz = make_quiz(created_by=str(bob.pk))
    asked = logged_in.get(url(bob, "delete"))
    assert asked.status_code == 200
    html = asked.content.decode()
    assert "bob" in html and f'action="{url(bob, "delete")}"' in html
    assert "csrfmiddlewaretoken" in html
    assert AdminUser.objects.filter(pk=bob.pk).exists()
    done = logged_in.post(url(bob, "delete"), {"confirm": "1"})
    assert done["Location"] == "/admin/users"
    assert not AdminUser.objects.filter(pk=bob.pk).exists()
    assert Quiz.objects.filter(pk=quiz.pk).exists()
    assert logged_in.get(f"/admin/quizzes/{quiz.pk}/edit").status_code == 200


def test_deleted_admin_is_logged_out(logged_in, bob, bob_client):
    logged_in.post(url(bob, "delete"), {"confirm": "1"})
    assert logged_out(bob_client)


def test_actions_on_an_unknown_admin_are_404(logged_in):
    from uuid import uuid7

    missing = f"/admin/admins/{uuid7()}/"
    assert logged_in.post(missing + "active", {"active": "0"}).status_code == 404
    assert logged_in.get(missing + "delete").status_code == 404


def test_actions_need_login(client, bob):
    for action in ("login", "password", "active", "delete"):
        response = client.post(url(bob, action), {"active": "0", "password": NEW})
        assert response.status_code == 302
    bob.refresh_from_db()
    assert bob.is_active and bob.check_password(GOOD)


def test_forms_on_a_refusal_page_post_to_their_own_address(logged_in, bob):
    """A refusal is drawn at the action's address; a form without `action` would post there."""
    pages = [
        logged_in.post(url(bob, "password"), {"password": "kratke"}),
        logged_in.post(url(bob, "login"), {"login": "alice"}),
        logged_in.post(url(AdminUser.objects.get(login="alice"), "active"), {"active": "0"}),
    ]
    for response in pages:
        assert response.status_code in (400, 409)
        html = response.content.decode()
        forms = re.findall(r"<form\b[^>]*>", html)
        posting = [form for form in forms if 'method="post"' in form]
        assert posting and all("action=" in form for form in posting), posting


@pytest.mark.parametrize("value", ["", "x", "2"])
def test_block_needs_an_explicit_value(logged_in, bob, value):
    data = {"active": value} if value else {}
    response = logged_in.post(url(bob, "active"), data)
    assert response.status_code == 400
    bob.refresh_from_db()
    assert bob.is_active


def test_a_second_delete_of_the_same_account_is_404(logged_in, bob, monkeypatch):
    """Two admins, or a double click, confirm the same deletion."""
    from app.domain import admins

    real_delete = admins.delete

    def deleted_meanwhile(admin, *, actor_id):
        AdminUser.objects.filter(pk=admin.pk).delete()
        real_delete(admin, actor_id=actor_id)

    monkeypatch.setattr(admins, "delete", deleted_meanwhile)
    assert logged_in.post(url(bob, "delete"), {"confirm": "1"}).status_code == 404


@pytest.mark.parametrize(
    ("action", "data"),
    [("active", {"active": "0"}), ("password", {"password": NEW}), ("login", {"login": "x"})],
)
def test_an_account_deleted_meanwhile_is_404(logged_in, bob, monkeypatch, action, data):
    from app.api import admin_users

    real = admin_users._admin

    def fetched_then_deleted(admin_id):
        admin = real(admin_id)
        AdminUser.objects.filter(pk=admin.pk).delete()
        return admin

    monkeypatch.setattr(admin_users, "_admin", fetched_then_deleted)
    assert logged_in.post(url(bob, action), data).status_code == 404
