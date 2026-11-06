import io
import json

import pytest
from django.contrib.auth import get_user
from django.core.management import CommandError, call_command

from app.kernel import audit
from app.kernel.models import AdminUser, AuditEvent
from app.providers.auth_local import passwords
from app.providers.auth_local.management.commands import init_admin, reset_admin_password

OLD = "old correct horse"
NEW = "new correct horse"


def init(login="alice", password=NEW):
    call_command("init_admin", login, password_stdin=True, stdin=io.StringIO(f"{password}\n"))


def reset(login="alice", password=NEW):
    call_command(
        "reset_admin_password", login, password_stdin=True, stdin=io.StringIO(f"{password}\n")
    )


def test_init_creates_first_admin_and_audits(db):
    init()
    user = AdminUser.objects.get()
    assert user.login == "alice"
    assert user.check_password(NEW)
    event = AuditEvent.objects.get()
    assert (event.action, event.actor_type, event.entity_type, event.entity_id) == (
        "admin.created",
        "cli",
        "admin",
        str(user.pk),
    )


def test_init_refused_when_an_admin_exists(db):
    existing = AdminUser.objects.create_admin("root", OLD)
    with pytest.raises(CommandError, match="already exists"):
        init()
    assert AdminUser.objects.get() == existing
    existing.refresh_from_db()
    assert existing.check_password(OLD)
    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("password", ["short", "", "password123"])
def test_init_rejects_weak_password(db, password):
    with pytest.raises(CommandError):
        init(password=password)
    assert not AdminUser.objects.exists()
    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("login", ["", "  ", "x" * 151])
def test_init_rejects_unusable_login(db, login):
    with pytest.raises(CommandError, match="login"):
        init(login=login)
    assert not AdminUser.objects.exists()


def test_init_rolls_back_when_audit_fails(db, monkeypatch):
    def fail(**kwargs):
        raise ZeroDivisionError

    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(ZeroDivisionError):
        init()
    assert not AdminUser.objects.exists()


def test_reset_changes_password_and_audits(db):
    user = AdminUser.objects.create_admin("alice", OLD)
    reset()
    user.refresh_from_db()
    assert user.check_password(NEW)
    assert not user.check_password(OLD)
    event = AuditEvent.objects.get()
    assert (event.action, event.actor_type, event.entity_id) == (
        "admin.password_reset",
        "cli",
        str(user.pk),
    )


def test_reset_revokes_existing_sessions(client, db):
    client.force_login(AdminUser.objects.create_admin("alice", OLD))
    assert get_user(client).is_authenticated
    reset()
    assert not get_user(client).is_authenticated


def test_reset_keeps_other_admins_sessions(client, db):
    client.force_login(AdminUser.objects.create_admin("bob", OLD))
    AdminUser.objects.create_admin("alice", OLD)
    reset()
    assert get_user(client).is_authenticated


def test_reset_unknown_login_refused(db):
    with pytest.raises(CommandError, match="nobody"):
        reset(login="nobody")
    assert not AuditEvent.objects.exists()


def test_reset_rolls_back_when_audit_fails(db, monkeypatch):
    def fail(**kwargs):
        raise ZeroDivisionError

    user = AdminUser.objects.create_admin("alice", OLD)
    monkeypatch.setattr(audit, "record", fail)
    with pytest.raises(ZeroDivisionError):
        reset()
    user.refresh_from_db()
    assert user.check_password(OLD)


@pytest.mark.parametrize("password", ["short", "", "password123"])
def test_reset_rejects_weak_password_and_keeps_old(db, password):
    user = AdminUser.objects.create_admin("alice", OLD)
    with pytest.raises(CommandError):
        reset(password=password)
    user.refresh_from_db()
    assert user.check_password(OLD)
    assert not AuditEvent.objects.exists()


def test_reset_reactivation_is_not_implied(db):
    AdminUser.objects.create_admin("alice", OLD)
    AdminUser.objects.update(is_active=False)
    reset()
    assert AdminUser.objects.get().is_active is False


def test_password_absent_from_output_and_audit(db, capsys):
    init()
    reset(password="another correct horse")
    out, err = capsys.readouterr()
    details = json.dumps(list(AuditEvent.objects.values_list("details_json", flat=True)))
    for text in (out, err, details):
        assert NEW not in text
        assert "another correct horse" not in text
    assert "alice" not in details


@pytest.mark.parametrize("module", [init_admin, reset_admin_password])
def test_commands_have_no_password_argument(module):
    parser = module.Command().create_parser("manage.py", "command")
    flags = {flag for action in parser._actions for flag in action.option_strings}
    assert "--password-stdin" in flags
    assert "--password" not in flags


def test_password_stdin_strips_only_the_newline(db):
    init(password="secret with space ")
    user = AdminUser.objects.get()
    assert user.check_password("secret with space ")
    assert not user.check_password("secret with space")


class Terminal(io.StringIO):
    def isatty(self):
        return True


def typed(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr(passwords, "getpass", lambda prompt: next(replies))


def test_interactive_input_asks_twice(db, monkeypatch):
    typed(monkeypatch, NEW, NEW)
    call_command("init_admin", "alice", stdin=Terminal())
    assert AdminUser.objects.get().check_password(NEW)


def test_interactive_mismatch_refused(db, monkeypatch):
    typed(monkeypatch, NEW, "different correct horse")
    with pytest.raises(CommandError, match="do not match"):
        call_command("init_admin", "alice", stdin=Terminal())
    assert not AdminUser.objects.exists()


def test_without_terminal_or_flag_refused_with_a_hint(db):
    with pytest.raises(CommandError, match="--password-stdin"):
        call_command("init_admin", "alice", stdin=io.StringIO(f"{NEW}\n"))
    assert not AdminUser.objects.exists()
