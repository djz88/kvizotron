import pytest

from app.kernel.models import AdminUser

PASSWORD = "dlouhe-a-neobvykle-heslo"


@pytest.fixture
def admin_user(db):
    return AdminUser.objects.create_admin("alice", PASSWORD)


@pytest.fixture
def logged_in(client, admin_user):
    client.force_login(admin_user)
    return client
