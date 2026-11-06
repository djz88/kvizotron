import pytest
from django.core.management import CommandError, call_command, get_commands

from app.kernel.models import AdminUser


@pytest.mark.parametrize(
    ("command", "alternative"),
    [("createsuperuser", "init_admin"), ("changepassword", "reset_admin_password")],
)
def test_django_password_command_refuses_and_names_ours(db, command, alternative):
    assert get_commands()[command] == "app.providers.auth_local"
    with pytest.raises(CommandError, match=alternative):
        call_command(command)
    assert not AdminUser.objects.exists()
