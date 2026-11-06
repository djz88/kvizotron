import uuid

import pytest

from app.contracts import AuthenticationProvider
from app.kernel.models import AdminUser


@pytest.mark.django_db
class AuthenticationContract:
    """Subclasses set `backend` and implement `account()`: a usable login and secret."""

    backend: AuthenticationProvider

    def account(self) -> tuple[str, str]:
        raise NotImplementedError

    def authenticate(self, login, secret):
        return self.backend.authenticate(None, username=login, password=secret)

    def test_satisfies_protocol(self):
        assert isinstance(self.backend, AuthenticationProvider)

    def test_correct_credentials_return_the_user(self):
        login, secret = self.account()
        assert self.authenticate(login, secret) == AdminUser.objects.get(login=login)

    def test_wrong_secret_returns_none(self):
        login, _ = self.account()
        assert self.authenticate(login, "definitely-wrong") is None

    def test_unknown_login_returns_none(self):
        _, secret = self.account()
        assert self.authenticate("nobody", secret) is None

    def test_inactive_account_returns_none(self):
        login, secret = self.account()
        AdminUser.objects.filter(login=login).update(is_active=False)
        assert self.authenticate(login, secret) is None

    def test_get_user_returns_the_user(self):
        login, _ = self.account()
        user = AdminUser.objects.get(login=login)
        assert self.backend.get_user(user.pk) == user

    def test_get_user_unknown_id_returns_none(self):
        assert self.backend.get_user(uuid.uuid7()) is None

    def test_get_user_inactive_returns_none(self):
        login, _ = self.account()
        AdminUser.objects.filter(login=login).update(is_active=False)
        assert self.backend.get_user(AdminUser.objects.get(login=login).pk) is None
