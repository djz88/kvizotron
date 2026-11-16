"""Changing and deleting admin accounts (AC-169). All admins are equal (ADR-0014).

Block and delete never leave the installation without an active admin and never act
on the account that asks. Block, delete and a new password end the account's sessions.
The audit carries the account id only: no login, e-mail or password.
"""

from importlib import import_module

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model, password_validation
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.utils import timezone

from app.kernel import audit


class AdminRefused(Exception):
    """The change would break a rule; nothing was saved."""


class LastAdmin(AdminRefused):
    """No other active admin would be left."""


class OwnAccount(AdminRefused):
    """An admin cannot block or delete their own account."""


class LoginTaken(AdminRefused):
    """Another account already has this login."""


class LoginInvalid(AdminRefused):
    """A login must have 1 to 150 characters."""


def _login_limit() -> int:
    return get_user_model()._meta.get_field("login").max_length


def _record(action: str, admin_id: str, actor_id: str) -> None:
    audit.record(
        actor_type="admin",
        actor_id=actor_id,
        action=action,
        entity_type="admin",
        entity_id=admin_id,
    )


def _ensure_may_lock_out(admin, actor_id: str) -> None:
    """Blocking or deleting `admin` must leave someone else able to log in."""
    if str(admin.pk) == str(actor_id):
        raise OwnAccount
    others = get_user_model().objects.filter(is_active=True).exclude(pk=admin.pk)
    if admin.is_active and not others.exists():
        raise LastAdmin


def rename(admin, login: str, *, actor_id: str) -> None:
    login = login.strip()
    if not login or len(login) > _login_limit():
        raise LoginInvalid
    if login == admin.login:
        return
    manager = get_user_model().objects
    try:
        with transaction.atomic():
            if manager.filter(login=login).exclude(pk=admin.pk).exists():
                raise LoginTaken
            if not manager.filter(pk=admin.pk).update(login=login):
                raise manager.model.DoesNotExist
            _record("admin.renamed", str(admin.pk), actor_id)
    except IntegrityError as error:  # the same login saved at the same moment
        raise LoginTaken from error
    admin.login = login


def set_password(
    admin, password: str, *, actor_id: str, keep_session_key: str | None = None
) -> None:
    """Raises `ValidationError` for a password the validators refuse; nothing is saved."""
    password_validation.validate_password(password, admin)
    admin.set_password(password)
    manager = get_user_model().objects
    with transaction.atomic():
        if not manager.filter(pk=admin.pk).update(password=admin.password):
            raise manager.model.DoesNotExist  # deleted meanwhile
        end_sessions(admin, keep_session_key=keep_session_key)
        _record("admin.password_set", str(admin.pk), actor_id)


def set_active(admin, active: bool, *, actor_id: str) -> None:
    """Raises `DoesNotExist` for an account deleted meanwhile, as `rename`, `delete` do."""
    with transaction.atomic():
        admin.refresh_from_db(fields=["is_active"])
        if admin.is_active == active:
            return
        if not active:
            _ensure_may_lock_out(admin, actor_id)
        admin.is_active = active
        admin.save(update_fields=["is_active"])
        if not active:
            end_sessions(admin)
        _record("admin.unblocked" if active else "admin.blocked", str(admin.pk), actor_id)


def delete(admin, *, actor_id: str) -> None:
    """Quizzes keep their `created_by`; their footer then has no author e-mail."""
    admin_id = str(admin.pk)
    with transaction.atomic():
        admin.refresh_from_db(fields=["is_active"])
        _ensure_may_lock_out(admin, actor_id)
        end_sessions(admin)
        admin.delete()
        _record("admin.deleted", admin_id, actor_id)


def end_sessions(admin, *, keep_session_key: str | None = None) -> int:
    """Delete every stored session logged in as `admin`, except `keep_session_key`."""
    admin_id = str(admin.pk)
    live = Session.objects.filter(expire_date__gt=timezone.now())
    ended = [
        session.session_key
        for session in live.exclude(session_key=keep_session_key or "")
        if str(session.get_decoded().get(SESSION_KEY)) == admin_id
    ]
    Session.objects.filter(session_key__in=ended).delete()
    return len(ended)


def clear_expired_sessions() -> None:
    """Delete expired login sessions; the `jobs` pass calls it, nothing else removes them."""
    import_module(settings.SESSION_ENGINE).SessionStore.clear_expired()
