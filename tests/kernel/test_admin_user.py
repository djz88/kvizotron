import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.db import IntegrityError

from app.kernel.models import AdminUser

PASSWORD = "correct horse battery"


def test_password_is_stored_with_argon2id(db):
    user = AdminUser.objects.create_admin("alice", PASSWORD)
    assert user.password.startswith("argon2$argon2id$")


def test_password_never_stored_in_clear(db):
    user = AdminUser.objects.create_admin("alice", PASSWORD)
    assert PASSWORD not in user.password


def test_only_argon2_can_hash_passwords():
    assert settings.PASSWORD_HASHERS == ["django.contrib.auth.hashers.Argon2PasswordHasher"]


def test_id_is_uuid7(db):
    assert AdminUser.objects.create_admin("alice", PASSWORD).pk.version == 7


def test_login_is_unique(db):
    AdminUser.objects.create_admin("alice", PASSWORD)
    with pytest.raises(IntegrityError):
        AdminUser.objects.create_admin("alice", "another password here")


@pytest.mark.parametrize("login", ["", "   ", "x" * 151])
def test_unusable_login_rejected(db, login):
    with pytest.raises(ValueError, match="login"):
        AdminUser.objects.create_admin(login, PASSWORD)
    assert not AdminUser.objects.exists()


def test_several_admins_are_independent(db):
    alice = AdminUser.objects.create_admin("alice", PASSWORD)
    bob = AdminUser.objects.create_admin("bob", "another password here")
    assert alice.pk != bob.pk
    assert alice.check_password(PASSWORD)
    assert not bob.check_password(PASSWORD)


def test_no_email_field():
    assert "email" not in {field.name for field in AdminUser._meta.get_fields()}


def test_session_settings():
    assert settings.SESSION_COOKIE_AGE == 43200
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"


def test_session_survives_until_password_changes(client, db):
    user = AdminUser.objects.create_admin("alice", PASSWORD)
    client.force_login(user)
    assert get_user(client).is_authenticated
    user.set_password("another password here")
    user.save()
    assert not get_user(client).is_authenticated
