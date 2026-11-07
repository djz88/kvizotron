import pytest

from app.kernel.models import AdminUser, AuditEvent
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
