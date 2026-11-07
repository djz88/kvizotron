"""Fetches an image by its address (ADR-0043). Only the standard library, and never trusts a name.

A name is resolved here and the connection goes to that checked address, so a second lookup cannot
answer differently. The certificate is still checked against the name.
"""

import http.client
import ipaddress
import socket
import ssl
import time
from collections.abc import Mapping, Sequence
from urllib.parse import quote, urljoin, urlsplit

MAX_REDIRECTS = 3
MAX_ADDRESS_LENGTH = 2000
READ_CHUNK = 64 * 1024
REDIRECTS = (301, 302, 303, 307, 308)
SAFE_IN_TARGET = "%/:=&?~#+!$,;'@()*[]-._"


class RemoteRefused(Exception):
    """The address cannot be used. The reason is for logs and tests, not for the admin."""


class RemoteInternal(RemoteRefused):
    """The address points inside the network and the switch is off."""


def check_address(url: str) -> None:
    """A well-formed `https://` address without credentials, or `RemoteRefused`."""
    if not url or len(url) > MAX_ADDRESS_LENGTH:
        raise RemoteRefused("address length")
    try:
        parts = urlsplit(url)
        _ = parts.port  # raises on a bad port
    except ValueError as exc:
        raise RemoteRefused("address form") from exc
    if parts.scheme != "https" or not parts.hostname:
        raise RemoteRefused("not https")
    if parts.username is not None or parts.password is not None:
        raise RemoteRefused("credentials in the address")


def _is_internal(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    ip = mapped or ip
    return not ip.is_global or ip.is_multicast or ip.is_reserved


def _resolved(host: str, port: int, allow_internal: bool) -> list[str]:
    """The addresses to try. Every answer must pass, since any of them could be used."""
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise RemoteRefused("name does not resolve") from exc
    addresses = [str(answer[4][0]) for answer in answers]
    if not addresses:
        raise RemoteRefused("name has no address")
    if not allow_internal and any(_is_internal(address) for address in addresses):
        raise RemoteInternal(host)
    return addresses


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, ip: str, timeout: float) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls)
        self._ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._tls.wrap_socket(raw, server_hostname=self.host)


def _request(
    url: str, ip: str, deadline: float, max_bytes: int
) -> tuple[int, Mapping[str, str], bytes]:
    parts = urlsplit(url)
    target = quote(parts.path or "/", safe=SAFE_IN_TARGET)
    if parts.query:
        target += "?" + quote(parts.query, safe=SAFE_IN_TARGET)
    remaining = deadline - time.monotonic()
    connection = _PinnedConnection(str(parts.hostname), parts.port or 443, ip, remaining)
    try:
        connection.request("GET", target, headers={"User-Agent": "Kvizotron", "Accept": "image/*"})
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        body = bytearray()
        while len(body) <= max_bytes:
            # A slow server is cut off by the deadline, not by a timeout on each read.
            if time.monotonic() >= deadline:
                raise RemoteRefused("too slow")
            chunk = response.read1(READ_CHUNK)
            if not chunk:
                break
            body += chunk
        return response.status, headers, bytes(body)
    finally:
        connection.close()


def _first_answer(
    url: str, ips: Sequence[str], deadline: float, max_bytes: int
) -> tuple[int, Mapping[str, str], bytes]:
    """A host may have an address this server has no route to, such as IPv6 in a container."""
    failure: Exception = RemoteRefused("no address")
    for ip in ips:
        try:
            return _request(url, ip, deadline, max_bytes)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            failure = exc
    raise RemoteRefused(type(failure).__name__) from failure


def fetch(url: str, *, allow_internal: bool, timeout: float, max_bytes: int) -> bytes:
    """The bytes at the address, following up to `MAX_REDIRECTS` checked redirects."""
    if timeout <= 0:
        raise RemoteRefused("no time left")
    deadline = time.monotonic() + timeout
    for _ in range(MAX_REDIRECTS + 1):
        check_address(url)
        parts = urlsplit(url)
        ips = _resolved(str(parts.hostname), parts.port or 443, allow_internal)
        status, headers, body = _first_answer(url, ips, deadline, max_bytes)
        if status in REDIRECTS:
            target = headers.get("location")
            if not target:
                raise RemoteRefused("redirect without a target")
            url = urljoin(url, target)
            continue
        if status != http.client.OK:
            raise RemoteRefused(f"status {status}")
        if len(body) > max_bytes:
            raise RemoteRefused("too large")
        return body
    raise RemoteRefused("too many redirects")
