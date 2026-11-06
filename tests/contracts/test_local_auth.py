from app.kernel.models import AdminUser
from app.providers.auth_local.backends import LocalBackend
from tests.contracts.authentication import AuthenticationContract


class TestLocalAuth(AuthenticationContract):
    backend = LocalBackend()

    def account(self):
        AdminUser.objects.create_admin("alice", "correct horse battery")
        return "alice", "correct horse battery"
