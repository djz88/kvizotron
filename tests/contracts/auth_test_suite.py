"""Run by test_auth_test_provider.py with auth.test installed; not collected on its own."""

from kvz_auth_test.backends import TOKEN, TokenBackend

from app.kernel.models import AdminUser
from tests.contracts.authentication import AuthenticationContract


class TestTokenAuth(AuthenticationContract):
    backend = TokenBackend()

    def account(self):
        AdminUser.objects.create_admin("alice", "unused password here")
        return "alice", TOKEN
