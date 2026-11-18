"""D5: one in-memory limiter with five buckets over a sliding minute."""

import sys
import threading
from pathlib import Path

import pytest

from app.api import rate_limit
from tests.support.run import run_python


@pytest.fixture(autouse=True)
def fresh_limiter():
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_a_bucket_allows_up_to_its_limit_then_refuses(settings):
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 3
    now = 1000.0
    for _ in range(3):
        assert rate_limit.allow("code", "1.2.3.4", now)
        rate_limit.record("code", "1.2.3.4", now)
    assert not rate_limit.allow("code", "1.2.3.4", now + 30)
    assert rate_limit.allow("code", "1.2.3.4", now + 60)  # exactly a minute old is dropped
    assert rate_limit.allow("code", "1.2.3.4", now + 61)


def test_buckets_and_keys_are_independent(settings):
    settings.KVZ_LOGIN_ATTEMPTS_PER_MINUTE = 1
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 1
    rate_limit.record("login", "1.2.3.4", 0.0)
    assert not rate_limit.allow("login", "1.2.3.4", 1.0)
    assert rate_limit.allow("login", "5.6.7.8", 1.0)
    assert rate_limit.allow("code", "1.2.3.4", 1.0)


def test_an_unknown_bucket_raises():
    with pytest.raises(KeyError):
        rate_limit.allow("nope", "1.2.3.4", 0.0)
    with pytest.raises(KeyError):
        rate_limit.record("nope", "1.2.3.4", 0.0)


def test_client_ip_is_the_value_the_nearest_trusted_proxy_wrote(rf, settings):
    """A client may send its own X-Forwarded-For; only the values our proxies add count."""
    request = rf.get("/", HTTP_X_FORWARDED_FOR=" 6.6.6.6 , 1.1.1.1 ", REMOTE_ADDR="3.3.3.3")
    settings.KVZ_TRUSTED_PROXIES = 1  # Caddy or one ingress: it appends the address it saw
    assert rate_limit.client_ip(request) == "1.1.1.1"
    settings.KVZ_TRUSTED_PROXIES = 2  # a load balancer in front of the ingress
    assert rate_limit.client_ip(request) == "6.6.6.6"
    settings.KVZ_TRUSTED_PROXIES = 0  # reached directly: the header is the client's own
    assert rate_limit.client_ip(request) == "3.3.3.3"


def test_fewer_forwarded_values_than_proxies_take_the_first(rf, settings):
    settings.KVZ_TRUSTED_PROXIES = 3
    request = rf.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2", REMOTE_ADDR="3.3.3.3")
    assert rate_limit.client_ip(request) == "1.1.1.1"
    assert rate_limit.client_ip(rf.get("/", REMOTE_ADDR="3.3.3.3")) == "3.3.3.3"


def test_caddy_writes_one_value_so_the_default_takes_it(rf):
    """Compose: Caddy replaces the header with the one address it saw (ADR-0058)."""
    request = rf.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1", REMOTE_ADDR="172.18.0.5")
    assert rate_limit.client_ip(request) == "1.1.1.1"


def test_a_blank_address_becomes_unknown_and_does_not_raise(rf):
    request = rf.get("/", REMOTE_ADDR="")
    assert rate_limit.client_ip(request) == "unknown"
    request.META.pop("REMOTE_ADDR")
    assert rate_limit.client_ip(request) == "unknown"
    blank_forwarded = rf.get("/", HTTP_X_FORWARDED_FOR="  ", REMOTE_ADDR="")
    assert rate_limit.client_ip(blank_forwarded) == "unknown"


def test_retry_after_is_a_minute():
    assert rate_limit.retry_after() == "60"


def test_idle_keys_are_swept_past_1000_tracked():
    for number in range(1000):
        rate_limit.record("submit", f"10.0.{number // 250}.{number % 250}", 0.0)
    assert rate_limit.tracked() == 1000
    rate_limit.record("submit", "10.9.9.9", 1000.0)
    assert rate_limit.tracked() == 1
    rate_limit.record("start", "10.8.8.8", 1000.0)
    rate_limit.sweep(5000.0)
    assert rate_limit.tracked() == 0


@pytest.fixture
def fast_thread_switching():
    """Switch threads every microsecond so a missing lock loses updates."""
    saved = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(saved)


def test_it_holds_under_50_threads(settings, fast_thread_switching):
    settings.KVZ_SUBMITS_PER_MINUTE = 100
    barrier = threading.Barrier(50)

    def work():
        barrier.wait()
        for _ in range(2):
            rate_limit.record("submit", "1.2.3.4", 10.0)

    threads = [threading.Thread(target=work) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert rate_limit.tracked() == 1
    assert not rate_limit.allow("submit", "1.2.3.4", 10.0)  # exactly 100 recorded
    settings.KVZ_SUBMITS_PER_MINUTE = 101
    assert rate_limit.allow("submit", "1.2.3.4", 10.0)
    settings.KVZ_SUBMITS_PER_MINUTE = 100
    assert rate_limit.allow("submit", "1.2.3.4", 71.0)


def test_defaults(tmp_path):
    """Read in a fresh process without any KVZ_* variable, so the environment cannot change them."""
    result = run_python(
        "from django.conf import settings\n"
        "print(settings.KVZ_LOGIN_ATTEMPTS_PER_MINUTE, settings.KVZ_CODE_ATTEMPTS_PER_MINUTE,"
        " settings.KVZ_SUBMITS_PER_MINUTE, settings.KVZ_STARTS_PER_MINUTE,"
        " settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE)\n",
        db=tmp_path / "db.sqlite3",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["5", "10", "120", "300", "30"]
    assert rate_limit.BUCKETS == ("login", "code", "submit", "start", "login_address")


def test_try_acquire_reserves_and_refuses_past_the_limit(settings):
    """AC-140: a slot is taken with the check, so the one past the limit is refused."""
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 3
    assert [rate_limit.try_acquire("code", "1.2.3.4", 10.0) for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    assert rate_limit.try_acquire("code", "5.6.7.8", 10.0)  # another key has its own slots
    assert rate_limit.try_acquire("code", "1.2.3.4", 70.0)  # the old slots left the window
    with pytest.raises(KeyError):
        rate_limit.try_acquire("nope", "1.2.3.4", 0.0)
    assert rate_limit.tracked() == 2


def test_a_refused_acquire_takes_nothing(settings):
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 1
    assert rate_limit.try_acquire("code", "1.2.3.4", 10.0)
    assert not rate_limit.try_acquire("code", "1.2.3.4", 40.0)
    assert rate_limit.try_acquire("code", "1.2.3.4", 70.0)  # the refusal at 40 stored nothing


def test_release_gives_back_the_newest_slot(settings):
    """AC-140: a correct login gives its slot back, the newest one."""
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 2
    assert rate_limit.try_acquire("code", "1.2.3.4", 10.0)
    assert rate_limit.try_acquire("code", "1.2.3.4", 20.0)
    assert not rate_limit.try_acquire("code", "1.2.3.4", 30.0)
    rate_limit.release("code", "1.2.3.4")
    assert rate_limit.try_acquire("code", "1.2.3.4", 30.0)
    assert not rate_limit.try_acquire("code", "1.2.3.4", 30.0)
    assert rate_limit.try_acquire("code", "1.2.3.4", 70.0)  # only the slot of 10.0 expired
    assert not rate_limit.try_acquire("code", "1.2.3.4", 70.0)


def test_release_of_an_unknown_key_does_nothing(settings):
    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 1
    rate_limit.release("code", "9.9.9.9")
    assert rate_limit.tracked() == 0
    assert rate_limit.try_acquire("code", "1.2.3.4", 10.0)
    rate_limit.release("code", "1.2.3.4")
    assert rate_limit.tracked() == 0  # the key is dropped with its last slot
    rate_limit.release("code", "1.2.3.4")
    assert rate_limit.try_acquire("code", "1.2.3.4", 10.0)


def test_try_acquire_never_exceeds_the_limit_under_threads(settings, fast_thread_switching):
    """AC-140: parallel acquires never pass the limit."""
    settings.KVZ_LOGIN_ATTEMPTS_PER_MINUTE = 5
    barrier = threading.Barrier(50)
    results: list[bool] = []

    def work():
        barrier.wait()
        results.append(rate_limit.try_acquire("login", "alice|1.2.3.4", 10.0))

    threads = [threading.Thread(target=work) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 50
    assert results.count(True) == 5


def test_the_ceiling_default_is_30_and_a_bad_value_is_refused(tmp_path):
    code = (
        "from django.conf import settings\nprint(settings.KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE)\n"
    )
    result = run_python(code, db=tmp_path / "db.sqlite3")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["30"]
    bad = run_python(
        code,
        db=tmp_path / "db2.sqlite3",
        env={"KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE": "0"},
    )
    assert bad.returncode != 0
    assert "KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE must be a positive integer" in bad.stderr


def test_compose_passes_the_ceiling_through_as_empty_by_default():
    compose = (Path(__file__).parents[2] / "deploy" / "compose.yaml").read_text()
    name = "KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE"
    assert f"    {name}: ${{{name}:-}}" in compose


def test_a_header_of_separators_only_falls_back_to_the_connection(rf):
    request = rf.get("/", HTTP_X_FORWARDED_FOR=" , ,", REMOTE_ADDR="3.3.3.3")
    assert rate_limit.client_ip(request) == "3.3.3.3"


def test_a_repeat_of_the_same_attempt_counts_once(settings):
    """TD-091, ADR-0058: a repeat of an attempt already counted takes no place in the bucket."""
    settings.KVZ_SUBMITS_PER_MINUTE = 2
    for _ in range(1 + rate_limit.FREE_REPEATS):  # the first send and its free repeats
        assert rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-a", now=100.0)
    assert rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-b", now=101.0)
    assert not rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-c", now=102.0)


def test_a_counted_attempt_is_forgotten_after_the_window(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 2
    later = rate_limit.WINDOW + 2  # a (sent at 0) is forgotten, b (sent at 30) is still counted
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)
    assert rate_limit.try_acquire_once("submit", "k", "b", now=30.0)
    assert rate_limit.try_acquire_once("submit", "k", "a", now=later)  # counts again: b + a = 2
    assert not rate_limit.try_acquire_once("submit", "k", "c", now=later + 1)  # bucket full


def test_a_repeat_does_not_extend_the_window_of_its_attempt(settings):
    """The memory of an attempt runs a window from its first counted send, never sliding."""
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)  # takes the one place
    assert rate_limit.try_acquire_once("submit", "k", "a", now=59.0)  # a free repeat
    assert rate_limit.try_acquire_once("submit", "k", "a", now=61.0)  # counts again: the place
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=61.0)  # so the bucket is full


def test_a_send_exactly_one_window_after_the_first_counts_again(settings):
    """The window is `>=`: at t = WINDOW the attempt is forgotten and its send takes a place."""
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)  # takes the one place
    assert rate_limit.try_acquire_once("submit", "k", "a", now=rate_limit.WINDOW - 0.001)  # free
    # at the boundary the place of the first send is also gone from the bucket, so it counts again
    assert rate_limit.try_acquire_once("submit", "k", "a", now=rate_limit.WINDOW)
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=rate_limit.WINDOW)  # place taken


def test_the_free_repeats_are_eight(settings):
    """The page repeats an automatic submission at most 6 times after errors and 2 after a 429."""
    assert rate_limit.FREE_REPEATS == 8


def test_a_ninth_repeat_in_the_window_counts_like_a_new_send(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)  # takes the one place
    for moment in range(1, 1 + rate_limit.FREE_REPEATS):
        assert rate_limit.try_acquire_once("submit", "k", "a", now=float(moment))
    assert not rate_limit.try_acquire_once("submit", "k", "a", now=9.0)  # the 9th: bucket full
    assert not rate_limit.try_acquire_once("submit", "k", "a", now=30.0)  # still in the window


def test_repeats_past_the_free_ones_take_places(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 3
    for _ in range(1 + rate_limit.FREE_REPEATS):
        assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)
    assert rate_limit.try_acquire_once("submit", "k", "a", now=1.0)  # the 9th takes a place
    assert rate_limit.try_acquire_once("submit", "k", "a", now=2.0)  # the 10th takes the last
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=3.0)
    assert not rate_limit.try_acquire_once("submit", "k", "a", now=3.0)
    # The window of a ended at 60 and the places at 0 and 1 have left it: a new first send.
    assert rate_limit.try_acquire_once("submit", "k", "a", now=61.0)
    for _ in range(rate_limit.FREE_REPEATS):
        assert rate_limit.try_acquire_once("submit", "k", "a", now=61.5)
    assert rate_limit.try_acquire_once("submit", "k", "b", now=61.5)  # free repeats took nothing


def test_a_counted_attempt_is_remembered_per_address(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "1.1.1.1", "a", now=0.0)
    assert rate_limit.try_acquire_once("submit", "2.2.2.2", "a", now=1.0)  # its own place there
    assert not rate_limit.try_acquire_once("submit", "1.1.1.1", "b", now=2.0)
    assert not rate_limit.try_acquire_once("submit", "2.2.2.2", "b", now=2.0)


def test_a_refused_attempt_is_not_remembered(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=1.0)
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=2.0)  # still not counted
    assert rate_limit.tracked() == 2  # the key of the bucket and attempt a, nothing for b
    with pytest.raises(KeyError):
        rate_limit.try_acquire_once("nope", "k", "a", now=0.0)


def test_sweep_and_reset_forget_counted_attempts(settings):
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)
    assert rate_limit.tracked() == 2
    rate_limit.sweep(100.0)
    assert rate_limit.tracked() == 0
    assert rate_limit.try_acquire_once("submit", "k", "a", now=200.0)
    rate_limit.reset()
    assert rate_limit.try_acquire_once("submit", "k", "a", now=201.0)  # counted again: the place
    assert not rate_limit.try_acquire_once("submit", "k", "b", now=201.0)


def test_counted_attempts_count_towards_the_sweep(settings):
    """Memory stays bounded: remembered attempts are swept with the idle keys past 1000 tracked."""
    settings.KVZ_SUBMITS_PER_MINUTE = 2000
    for number in range(999):
        assert rate_limit.try_acquire_once("submit", "1.2.3.4", f"attempt-{number}", now=0.0)
    assert rate_limit.tracked() == 1000  # one key and 999 attempts
    assert rate_limit.try_acquire_once("submit", "5.6.7.8", "attempt-x", now=1000.0)
    assert rate_limit.tracked() == 2


def test_parallel_repeats_take_one_place(settings, fast_thread_switching):
    """TD-091: parallel sends of one attempt pass together and take one place between them."""
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    barrier = threading.Barrier(8)
    results: list[bool] = []

    def work():
        barrier.wait()
        results.append(rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-a", 10.0))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True] * 8
    assert not rate_limit.allow("submit", "1.2.3.4", 10.0)  # at least one event
    settings.KVZ_SUBMITS_PER_MINUTE = 2
    assert rate_limit.allow("submit", "1.2.3.4", 10.0)  # and only one
