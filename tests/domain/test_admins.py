"""Editing and deleting admin accounts: rules, sessions and audit (AC-169, ADR-0014)."""

from importlib import import_module

import pytest
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError

from app.domain import admins
from app.domain.models import Quiz
from app.kernel.models import AdminUser, AuditEvent

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-long-phrase-42"


def make(login, active=True):
    admin = AdminUser.objects.create_admin(login, PASSWORD)
    if not active:
        admin.is_active = False
        admin.save(update_fields=["is_active"])
    return admin


def session_of(admin) -> str:
    """A stored login session of `admin`, as the login view would leave it."""
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store[SESSION_KEY] = str(admin.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = admin.get_session_auth_hash()
    store.create()
    return store.session_key


def keys() -> set[str]:
    return set(Session.objects.values_list("session_key", flat=True))


def events(action):
    return list(AuditEvent.objects.filter(action=action))


def assert_no_personal_data(event, *values):
    text = f"{event.entity_id} {event.details_json} {event.actor_id}"
    for value in values:
        assert value not in text


@pytest.fixture
def alice():
    return make("alice")


@pytest.fixture
def bob():
    return make("bob")


# --- rename ---------------------------------------------------------------


def test_rename_saves_and_audits_without_the_login(alice, bob):
    admins.rename(bob, "robert", actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.login == "robert"
    [event] = events("admin.renamed")
    assert event.entity_type == "admin"
    assert event.entity_id == str(bob.pk)
    assert event.actor_id == str(alice.pk)
    assert_no_personal_data(event, "robert", "bob")


def test_rename_to_a_taken_login_is_refused(alice, bob):
    with pytest.raises(admins.LoginTaken):
        admins.rename(bob, "alice", actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.login == "bob"
    assert events("admin.renamed") == []


def test_rename_to_the_same_login_changes_nothing(alice):
    admins.rename(alice, "alice", actor_id=str(alice.pk))

    assert events("admin.renamed") == []


@pytest.mark.parametrize("login", ["", "   ", "x" * 151])
def test_rename_needs_1_to_150_characters(alice, bob, login):
    with pytest.raises(admins.LoginInvalid):
        admins.rename(bob, login, actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.login == "bob"


def test_rename_keeps_150_characters(alice, bob):
    admins.rename(bob, "x" * 150, actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.login == "x" * 150


def test_rename_strips_surrounding_spaces(alice, bob):
    admins.rename(bob, "  robert ", actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.login == "robert"


# --- password -------------------------------------------------------------


def test_set_password_changes_it_and_ends_the_accounts_sessions(alice, bob):
    theirs = session_of(bob)
    mine = session_of(alice)

    admins.set_password(bob, NEW_PASSWORD, actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.check_password(NEW_PASSWORD)
    assert theirs not in keys()
    assert mine in keys()
    [event] = events("admin.password_set")
    assert event.entity_id == str(bob.pk)
    assert_no_personal_data(event, NEW_PASSWORD, "bob")


def test_own_new_password_keeps_the_current_session(alice):
    current = session_of(alice)
    other_device = session_of(alice)

    admins.set_password(alice, NEW_PASSWORD, actor_id=str(alice.pk), keep_session_key=current)

    assert current in keys()
    assert other_device not in keys()


def test_weak_password_is_refused_and_nothing_saved(alice, bob):
    theirs = session_of(bob)

    with pytest.raises(ValidationError):
        admins.set_password(bob, "short", actor_id=str(alice.pk))

    bob.refresh_from_db()
    assert bob.check_password(PASSWORD)
    assert theirs in keys()
    assert events("admin.password_set") == []


# --- block ----------------------------------------------------------------


def test_block_and_unblock_are_audited_and_block_ends_sessions(alice, bob):
    theirs = session_of(bob)

    admins.set_active(bob, False, actor_id=str(alice.pk))
    bob.refresh_from_db()
    assert bob.is_active is False
    assert theirs not in keys()

    admins.set_active(bob, True, actor_id=str(alice.pk))
    bob.refresh_from_db()
    assert bob.is_active is True
    assert [e.entity_id for e in events("admin.blocked")] == [str(bob.pk)]
    assert [e.entity_id for e in events("admin.unblocked")] == [str(bob.pk)]


def test_blocking_oneself_is_refused(alice, bob):
    with pytest.raises(admins.OwnAccount):
        admins.set_active(alice, False, actor_id=str(alice.pk))

    alice.refresh_from_db()
    assert alice.is_active is True


def test_blocking_the_last_active_admin_is_refused(alice):
    blocked = make("carol", active=False)

    with pytest.raises(admins.LastAdmin):
        admins.set_active(alice, False, actor_id=str(blocked.pk))

    alice.refresh_from_db()
    assert alice.is_active is True
    assert events("admin.blocked") == []


def test_blocking_an_already_blocked_admin_changes_nothing(alice):
    carol = make("carol", active=False)

    admins.set_active(carol, False, actor_id=str(alice.pk))

    assert events("admin.blocked") == []


# --- delete ---------------------------------------------------------------


def test_delete_removes_the_account_and_its_sessions_and_keeps_its_quizzes(alice, bob):
    """AC-169: a deleted admin's sessions end, its quizzes stay, the audit keeps only the id."""
    theirs = session_of(bob)
    quiz = Quiz.objects.create(title={"cs": "Bobův kvíz"}, created_by=str(bob.pk))
    bob.email = "bob@example.org"
    bob.save(update_fields=["email"])
    bob_id = bob.pk

    admins.delete(bob, actor_id=str(alice.pk))

    assert not AdminUser.objects.filter(pk=bob_id).exists()
    assert theirs not in keys()
    assert Quiz.objects.filter(pk=quiz.pk, created_by=str(bob_id)).exists()
    [event] = events("admin.deleted")
    assert event.entity_id == str(bob_id)
    assert_no_personal_data(event, "bob@example.org", "bob")


def test_deleting_oneself_is_refused(alice, bob):
    with pytest.raises(admins.OwnAccount):
        admins.delete(alice, actor_id=str(alice.pk))

    assert AdminUser.objects.filter(pk=alice.pk).exists()


def test_deleting_the_last_active_admin_is_refused(alice):
    blocked = make("carol", active=False)

    with pytest.raises(admins.LastAdmin):
        admins.delete(alice, actor_id=str(blocked.pk))

    assert AdminUser.objects.filter(pk=alice.pk).exists()


def test_deleting_a_blocked_admin_is_allowed_with_one_active_left(alice):
    carol = make("carol", active=False)

    admins.delete(carol, actor_id=str(alice.pk))

    assert not AdminUser.objects.filter(pk=carol.pk).exists()


def test_refusals_share_one_base(alice):
    assert issubclass(admins.LastAdmin, admins.AdminRefused)
    assert issubclass(admins.OwnAccount, admins.AdminRefused)
    assert issubclass(admins.LoginTaken, admins.AdminRefused)
    assert issubclass(admins.LoginInvalid, admins.AdminRefused)


# --- sessions -------------------------------------------------------------


def test_end_sessions_leaves_other_accounts_and_anonymous_sessions(alice, bob):
    theirs = session_of(bob)
    mine = session_of(alice)
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store["kvz"] = "anonymous"
    store.create()

    assert admins.end_sessions(bob) == 1

    assert keys() == {mine, store.session_key}
    assert theirs not in keys()


def expire(session_key):
    from datetime import timedelta

    from django.utils import timezone

    Session.objects.filter(session_key=session_key).update(
        expire_date=timezone.now() - timedelta(minutes=1)
    )


def test_end_sessions_counts_only_live_sessions(alice, bob):
    live = session_of(bob)
    expire(session_of(bob))

    assert admins.end_sessions(bob) == 1
    assert live not in keys()


def test_clear_expired_sessions_keeps_live_ones(alice, bob):
    live = session_of(alice)
    old = session_of(bob)
    expire(old)

    admins.clear_expired_sessions()

    assert keys() == {live}
