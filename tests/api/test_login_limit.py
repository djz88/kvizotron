"""Failed admin logins are limited per name and address (ADR-0030); successes count nothing."""

import threading
import time
from types import SimpleNamespace

import pytest

from app.api import admin_auth, rate_limit
from tests.api.conftest import PASSWORD
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
WRONG = "spatne-heslo-12345"
REFUSED = "Too many attempts. Please try again in a minute."
REFUSED_CS = "Příliš mnoho pokusů. Zkuste to prosím za minutu."


@pytest.fixture(autouse=True)
def fresh_limiter(settings):
    settings.KVZ_LOGIN_ATTEMPTS_PER_MINUTE = 5
    rate_limit.reset()
    yield
    rate_limit.reset()


def login(client, password=PASSWORD, username="alice", ip="10.0.0.1", path="/admin/login"):
    data = {"login": username, "password": password}
    return client.post(path, data, HTTP_X_FORWARDED_FOR=ip)


def fail(client, times, **kwargs):
    for _ in range(times):
        assert login(client, WRONG, **kwargs).status_code == 200


def test_the_sixth_wrong_login_in_a_minute_is_refused(client, admin_user):
    """AC-129: the sixth wrong login for a name from one address in a minute is refused with 429."""
    for _ in range(5):
        response = login(client, WRONG)
        assert response.status_code == 200
        assert "Nesprávné přihlašovací jméno nebo heslo." in response.content.decode()
    response = login(client, WRONG)
    html = response.content.decode()
    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert "<form" in html and 'name="password"' in html
    assert "Příliš mnoho pokusů" in html


def test_a_correct_login_is_refused_while_the_bucket_is_full_but_counts_nothing(
    client, admin_user, monkeypatch
):
    """The chosen rule: a full bucket refuses even the right password until the window passes."""
    now = [100.0]
    monkeypatch.setattr(admin_auth, "time", SimpleNamespace(monotonic=lambda: now[0]))
    fail(client, 5)
    refused = login(client)
    assert refused.status_code == 429 and refused["Retry-After"] == "60"
    assert client.get("/admin/quizzes").status_code == 302
    now[0] += 30  # the refusal recorded nothing: the window still ends a minute after the failures
    assert login(client).status_code == 429
    now[0] += 31
    assert login(client).status_code == 302
    assert client.get("/admin/quizzes").status_code == 200


def test_failures_of_another_address_do_not_lock_this_one(client, admin_user):
    """AC-129: one address cannot lock the account for another."""
    fail(client, 5, ip="10.0.0.1")
    assert login(client, ip="10.0.0.1").status_code == 429
    response = login(client, ip="10.0.0.2")
    assert response.status_code == 302
    assert client.get("/admin/quizzes").status_code == 200


def test_failures_of_another_name_do_not_lock_this_one(client, admin_user):
    fail(client, 5, username="bob")
    assert login(client, username="bob").status_code == 429
    assert login(client).status_code == 302


def test_case_and_spaces_share_one_bucket(client, admin_user):
    for name in ("Alice", "alice ", "ALICE", " alice", "aLiCe"):
        assert login(client, WRONG, username=name).status_code == 200
    for name in ("alice", "Alice ", "ALICE"):
        assert login(client, WRONG, username=name).status_code == 429


def test_a_successful_login_is_not_counted(client, admin_user):
    """AC-129: a correct login counts nothing."""
    fail(client, 4)
    for _ in range(3):
        assert login(client).status_code == 302
        client.post("/admin/logout")
    assert login(client, WRONG).status_code == 200  # the fifth failure
    assert login(client, WRONG).status_code == 429


def test_a_request_without_a_valid_form_counts_nothing(client, admin_user):
    for _ in range(6):
        assert login(client, "", username="").status_code == 200
    assert login(client).status_code == 302


def test_the_message_is_translated(client, admin_user):
    fail(client, 5)
    english = login(client, WRONG, path="/admin/login?lang=en")
    assert english.status_code == 429 and REFUSED in english.content.decode()
    czech = login(client, WRONG, path="/admin/login?lang=cs")
    assert czech.status_code == 429 and REFUSED_CS in czech.content.decode()


def test_parallel_wrong_logins_never_exceed_the_limit(admin_user, monkeypatch, settings):
    """AC-140, AC-129: parallel wrong guesses reserve their slot first, so none slip past."""

    def slow_wrong(request, **credentials):
        time.sleep(0.05)
        return None

    monkeypatch.setattr(admin_auth, "authenticate", slow_wrong)
    barrier = threading.Barrier(20)
    statuses: list[int] = []

    def attempt():
        client = FormClient()
        barrier.wait()
        statuses.append(login(client, WRONG).status_code)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(statuses) == 20
    assert sum(1 for status in statuses if status != 429) == settings.KVZ_LOGIN_ATTEMPTS_PER_MINUTE
    assert statuses.count(429) == 15


def test_a_correct_login_leaves_the_slots_as_it_found_them(client, admin_user):
    """A correct login gives its slot back: the fifth failure is allowed, the sixth refused."""
    fail(client, 4)
    assert login(client).status_code == 302
    client.post("/admin/logout")
    assert login(client, WRONG).status_code == 200  # the fifth failure is still allowed
    assert login(client, WRONG).status_code == 429


def test_one_address_spraying_many_names_hits_the_ceiling(client, settings):
    """AC-140: one address guessing across many names is refused at its own ceiling."""
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 3
    for name in ("alice", "bob", "carol"):  # each name stays far below its own limit of 5
        assert login(client, WRONG, username=name).status_code == 200
    response = login(client, WRONG, username="dave")
    assert response.status_code == 429
    assert response["Retry-After"] == "60"
    assert REFUSED in response.content.decode() or REFUSED_CS in response.content.decode()


def test_the_ceiling_of_one_address_does_not_touch_another(client, admin_user, settings):
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 3
    for name in ("alice", "bob", "carol"):
        assert login(client, WRONG, username=name, ip="10.0.0.1").status_code == 200
    assert login(client, WRONG, username="dave", ip="10.0.0.1").status_code == 429
    assert login(client, WRONG, username="dave", ip="10.0.0.2").status_code == 200
    assert login(client, ip="10.0.0.2").status_code == 302


def test_a_correct_login_does_not_count_toward_the_ceiling(client, admin_user, settings):
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 3
    for _ in range(5):  # more correct logins than the ceiling allows wrong ones
        assert login(client).status_code == 302
        client.post("/admin/logout")
    for name in ("bob", "carol", "dave"):
        assert login(client, WRONG, username=name).status_code == 200
    assert login(client, WRONG, username="erin").status_code == 429


def test_a_correct_login_gives_back_both_slots(client, admin_user, settings):
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 3
    assert login(client, WRONG, username="bob").status_code == 200
    assert login(client, WRONG, username="carol").status_code == 200
    assert login(client).status_code == 302  # alice: takes and returns a slot in both buckets
    client.post("/admin/logout")
    assert rate_limit.tracked() == 3  # bob and carol by name, the address with two events
    assert login(client, WRONG, username="dave").status_code == 200  # the third wrong one
    assert login(client, WRONG, username="erin").status_code == 429


def test_a_refusal_by_either_bucket_looks_the_same(client, settings):
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 3
    fail(client, 3, username="alice", ip="10.0.0.5")
    by_ceiling = login(client, WRONG, username="dave", ip="10.0.0.5")
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 30
    fail(client, 5, username="frank", ip="10.0.0.6")
    by_name = login(client, WRONG, username="frank", ip="10.0.0.6")
    assert by_ceiling.status_code == by_name.status_code == 429
    assert by_ceiling["Retry-After"] == by_name["Retry-After"] == "60"
    assert by_ceiling.content.decode().count(REFUSED_CS) == 1
    assert by_name.content.decode().count(REFUSED_CS) == 1


def test_a_refusal_by_the_ceiling_gives_the_name_slot_back(client, settings):
    settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE = 2
    for name in ("alice", "bob"):
        assert login(client, WRONG, username=name).status_code == 200
    assert login(client, WRONG, username="carol").status_code == 429
    assert rate_limit.tracked() == 3  # alice and bob by name, the address; none for carol


def test_a_forged_left_hand_address_does_not_open_a_new_bucket(client, admin_user):
    """AC-182: only the address the trusted proxy appended counts, not what the client wrote."""
    for forged in range(5):
        assert login(client, WRONG, ip=f"6.6.6.{forged}, 10.0.0.1").status_code == 200
    assert login(client, WRONG, ip="7.7.7.7, 10.0.0.1").status_code == 429
