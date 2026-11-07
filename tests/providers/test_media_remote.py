"""Fetching an image by address. `getaddrinfo` and `_request` are replaced: no network here."""

import socket
from unittest import mock

import pytest

from app.providers.media_local import remote

URL = "https://a.cz/x.png"
PUBLIC = "93.184.216.34"


def fetch(url=URL, allow_internal=False, timeout=1, max_bytes=100):
    return remote.fetch(url, allow_internal=allow_internal, timeout=timeout, max_bytes=max_bytes)


@pytest.fixture
def resolves_to(monkeypatch):
    def configure(*addresses):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in addresses]
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: answers)

    configure(PUBLIC)
    return configure


@pytest.fixture
def responses(monkeypatch):
    """Answers in turn; each call is recorded as (url, ip)."""
    seen = []
    queue = []

    def fake(url, ip, deadline, max_bytes):
        seen.append((url, ip))
        return queue.pop(0)

    monkeypatch.setattr(remote, "_request", fake)
    return mock.Mock(seen=seen, queue=queue)


@pytest.mark.parametrize(
    "url",
    [
        "http://a.cz/x.png",
        "ftp://a.cz/x",
        "https://",
        "https://u:p@a.cz/x.png",
        "https://u@a.cz/x.png",
        "nonsense",
        "",
        "https://a.cz:notaport/x.png",
        "https://" + "a" * 3000 + ".cz/",
    ],
)
def test_a_bad_address_is_invalid(url):
    with pytest.raises(remote.RemoteRefused):
        remote.check_address(url)


def test_a_good_address_passes():
    remote.check_address("https://a.cz:8443/x.png?size=1")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_an_internal_address_is_refused_before_any_connection(ip, resolves_to, responses):
    resolves_to(ip)
    with pytest.raises(remote.RemoteInternal):
        fetch()
    assert responses.seen == []


def test_one_internal_address_among_several_is_enough(resolves_to, responses):
    resolves_to(PUBLIC, "10.0.0.1")
    with pytest.raises(remote.RemoteInternal):
        fetch()
    assert responses.seen == []


def test_the_switch_allows_an_internal_address(resolves_to, responses):
    resolves_to("192.168.1.5")
    responses.queue.append((200, {}, b"ok"))
    assert fetch(allow_internal=True) == b"ok"
    assert responses.seen == [(URL, "192.168.1.5")]


def test_the_connection_goes_to_the_checked_address(resolves_to, responses):
    responses.queue.append((200, {}, b"ok"))
    assert fetch() == b"ok"
    assert responses.seen == [(URL, PUBLIC)]


def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    def fail(*_args, **_kwargs):
        raise socket.gaierror("no such name")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(remote.RemoteRefused):
        fetch()


def test_a_redirect_is_followed_and_checked_again(resolves_to, responses):
    responses.queue += [(302, {"location": "/y.png"}, b""), (200, {}, b"ok")]
    assert fetch() == b"ok"
    assert responses.seen[1][0] == "https://a.cz/y.png"


def test_a_redirect_to_an_internal_address_is_refused(monkeypatch, responses):
    addresses = {"a.cz": PUBLIC, "b.cz": "10.0.0.1"}

    def resolve(host, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    responses.queue.append((302, {"location": "https://b.cz/x.png"}, b""))
    with pytest.raises(remote.RemoteInternal):
        fetch()
    assert len(responses.seen) == 1


def test_a_redirect_to_http_is_refused(resolves_to, responses):
    responses.queue.append((302, {"location": "http://a.cz/x.png"}, b""))
    with pytest.raises(remote.RemoteRefused):
        fetch()
    assert len(responses.seen) == 1


def test_three_redirects_pass_and_a_fourth_is_refused(resolves_to, responses):
    responses.queue += [(302, {"location": "/1"}, b"")] * 3 + [(200, {}, b"ok")]
    assert fetch() == b"ok"
    responses.seen.clear()
    responses.queue += [(302, {"location": "/1"}, b"")] * 4
    with pytest.raises(remote.RemoteRefused):
        fetch()
    assert len(responses.seen) == 4


def test_a_redirect_without_a_target_is_refused(resolves_to, responses):
    responses.queue.append((302, {}, b""))
    with pytest.raises(remote.RemoteRefused):
        fetch()


def test_too_many_bytes_are_refused(resolves_to, responses):
    responses.queue.append((200, {}, b"x" * 101))
    with pytest.raises(remote.RemoteRefused):
        fetch()


def test_an_error_status_is_refused(resolves_to, responses):
    responses.queue.append((404, {}, b"not here"))
    with pytest.raises(remote.RemoteRefused):
        fetch()


def test_a_passed_deadline_is_refused_without_a_connection(resolves_to, responses):
    with pytest.raises(remote.RemoteRefused):
        fetch(timeout=0)
    assert responses.seen == []


def test_a_broken_connection_is_refused(resolves_to, monkeypatch):
    def fail(*_args):
        raise OSError("connection refused")

    monkeypatch.setattr(remote, "_request", fail)
    with pytest.raises(remote.RemoteRefused):
        fetch()


def test_the_real_connection_uses_the_checked_address_and_verifies_the_name():
    with (
        mock.patch("socket.create_connection") as connect,
        mock.patch("ssl.create_default_context") as context,
    ):
        connection = remote._PinnedConnection("a.cz", 443, PUBLIC, 1.0)
        connection.connect()
    assert connect.call_args.args[0] == (PUBLIC, 443)
    wrap = context.return_value.wrap_socket
    assert wrap.call_args.kwargs["server_hostname"] == "a.cz"


def test_the_next_checked_address_is_tried_when_one_fails(resolves_to, monkeypatch):
    resolves_to("2606:2800:220:1:248:1893:25c8:1946", PUBLIC)
    tried = []

    def fake(url, ip, deadline, max_bytes):
        tried.append(ip)
        if len(tried) == 1:
            raise OSError("no route")
        return 200, {}, b"ok"

    monkeypatch.setattr(remote, "_request", fake)
    assert fetch() == b"ok"
    assert tried == ["2606:2800:220:1:248:1893:25c8:1946", PUBLIC]


def test_every_address_failing_is_refused(resolves_to, monkeypatch):
    resolves_to(PUBLIC, "93.184.216.35")
    fake = mock.Mock(side_effect=OSError("no route"))
    monkeypatch.setattr(remote, "_request", fake)
    with pytest.raises(remote.RemoteRefused):
        fetch()
    assert fake.call_count == 2


def test_a_server_that_answers_is_not_asked_again_at_another_address(resolves_to, responses):
    resolves_to(PUBLIC, "93.184.216.35")
    responses.queue.append((404, {}, b""))
    with pytest.raises(remote.RemoteRefused):
        fetch()
    assert len(responses.seen) == 1
