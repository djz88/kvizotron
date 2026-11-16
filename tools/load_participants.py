"""Fifty participants play one run at the same moment, with photos, and the answers are judged.

    python -m tools.load_participants --base https://localhost:18643 --run RUN_ID \\
        [--clients 50] [--photo-kb 700 | --photo-file PATH]

Every client starts an attempt, asks the page's `check` for each question when the form asks for
it (reveal after each question), waits at a barrier and then all of them send the submission at
once: a multipart form with a photo. The photo is the file of `--photo-file` (a real picture:
the server's decoding and conversion is most of the cost of a submit) or, without it, a valid
JPEG of about `--photo-kb` kilobytes made of a tiny picture and padding (it tests the upload,
not the decoding). After that the first few send the same submission again. One line per
criterion, `PASS`, `FAIL` or `INFO`; the exit code is non-zero when any is `FAIL`. The line
`WINDOW first=EPOCH last=EPOCH` gives the moment the first submit was sent and the last answer
arrived, for `deploy/load.sh` to compare with the backups. What only the database or the logs
know (each attempt once, each photo once, no lock) is checked by `deploy/load.sh`, not here.

    python -m tools.load_participants --base URL --run RUN_ID --probe-from LAN_ADDRESS

is the address probe: it shows whether the application counts distinct sources separately (the
start limit, ADR-0030). It sends starts from the given address until the limit refuses one
(`--probe-limit`, the application's setting, 300 by default), then one start each from 127.0.0.1
and 127.0.0.2. It passes when the refusal comes at start limit + 1 (the address is counted
apart from whatever the load sent before) and the loopback sources are still accepted. It does
not tell 127.0.0.1 and 127.0.0.2 apart from each other. Use a run of its own: every start
makes an attempt.

Standard library only. The self-signed certificate of a local deployment is accepted only for
localhost.
"""

import argparse
import base64
import http.client
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path

TOKEN = re.compile(r'name="attempt_token" value="([^"]+)"')
KEY = re.compile(r'name="submission_key" value="([^"]+)"')
ATTEMPT = re.compile(r"/a/([0-9a-f-]{36})/submit")
QUESTION = re.compile(r'data-question="([^"]+)"')
CHECKING = re.compile(r"data-flow-check[ >]")  # the form asks for a reveal after each question
PHOTO = re.compile(r'name="([^"]+:image)"')
RADIO = re.compile(
    r'name="([^"]+:options\[\])"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*name="([^"]+:options\[\])"'
)
SIGNED = re.compile(r"/v/[\w:-]+")  # the private link carries the moment it was made
LIMIT_SECONDS = 5.0
REPEATING = 5
REQUEST_SECONDS = 60
BARRIER_SECONDS = 120
TOTAL_SECONDS = 300.0  # for the whole pass, starts to answers
NETWORK = (OSError, http.client.HTTPException)
LOOPBACK = ("127.0.0.1", "127.0.0.2")

# A valid 32x32 JPEG (645 bytes). Comment segments are added to reach the size asked for: the
# decoder skips them, and random bytes do not compress away on the way.
SMALL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIx"
    "wcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAgACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAw"
    "QFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmq"
    "KjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEB"
    "AQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRob"
    "HBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+P"
    "n6/9oADAMBAAIRAxEAPwDl6KKK8c/RwooooAKKKKACiiigD//Z"
)


def _context(base: str) -> ssl.SSLContext | None:
    host = urllib.parse.urlsplit(base).hostname
    if not base.startswith("https") or host != "localhost":
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def photo(kilobytes: int) -> bytes:
    """A valid JPEG of about the given size: the small picture and comment segments of noise."""
    padding = max(0, kilobytes * 1024 - len(SMALL_JPEG))
    after_jfif = 20  # the start marker and the JFIF segment
    comments = b""
    while padding > 4:
        size = min(padding - 4, 65000)
        comments += b"\xff\xfe" + (size + 2).to_bytes(2, "big") + os.urandom(size)
        padding -= size + 4
    return SMALL_JPEG[:after_jfif] + comments + SMALL_JPEG[after_jfif:]


def multipart(fields: dict[str, str], files: dict[str, bytes]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    for name, data in files.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="foto.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True)
class Source:
    """Where a request comes from: connect to `address` (the base's host when empty), from
    `bind` (the system chooses when empty). The Host header stays the base's host name."""

    address: str = ""
    bind: str = ""


def post(
    base: str,
    path: str,
    body: bytes,
    content_type: str,
    context: ssl.SSLContext | None,
    source: Source | None = None,
) -> tuple[int, str]:
    source = source or Source()
    parts = urllib.parse.urlsplit(base)
    host = parts.hostname or ""
    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    where = (source.bind, 0) if source.bind else None
    connection: http.client.HTTPConnection
    if secure:
        connection = http.client.HTTPSConnection(
            source.address or host,
            port,
            timeout=REQUEST_SECONDS,
            context=context,
            source_address=where,
        )
    else:
        connection = http.client.HTTPConnection(
            source.address or host, port, timeout=REQUEST_SECONDS, source_address=where
        )
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": content_type, "Host": parts.netloc},
        )
        response = connection.getresponse()
        return response.status, response.read().decode(errors="replace")
    finally:
        connection.close()


@dataclass
class Client:
    number: int
    start: int = 0
    checks: list[int] = field(default_factory=list)
    submit: int = 0
    seconds: float = 0.0
    page: str = ""
    path: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    photo_field: str = ""
    questions: list[str] = field(default_factory=list)
    error: str = ""
    sent_at: float = 0.0  # epoch of the submit sent and of its answer
    answered_at: float = 0.0


def _submission(client: Client, jpeg: bytes) -> tuple[bytes, str]:
    """Multipart with the photo where the page has a photo field; the application takes
    multipart from an attempt with a photo question only."""
    if client.photo_field:
        return multipart(client.fields, {client.photo_field: jpeg})
    return form(client.fields)


def form(fields: dict[str, str]) -> tuple[bytes, str]:
    return urllib.parse.urlencode(fields).encode(), "application/x-www-form-urlencoded"


def _wait(barrier: threading.Barrier, client: Client) -> None:
    try:
        barrier.wait(BARRIER_SECONDS)
    except threading.BrokenBarrierError:
        client.error = client.error or "barrier: another client did not arrive in time"


def _play(
    client: Client,
    base: str,
    run: str,
    context: ssl.SSLContext | None,
    jpeg: bytes,
    barriers: tuple[threading.Barrier, threading.Barrier],
) -> None:
    after_start, after_checks = barriers
    try:
        client.start, html = post(base, f"/r/{run}/start", *form({"lang": "cs"}), context)
        if client.start != 200:
            raise AssertionError(f"start answered {client.start}")
        attempt = ATTEMPT.findall(html)[0]
        client.path = f"/a/{attempt}/submit"
        answers: dict[str, str] = {}
        for name, value, other_value, other_name in RADIO.findall(html):
            answers.setdefault(name or other_name, value or other_value)
        client.fields = {
            "attempt_token": TOKEN.findall(html)[0],
            "submission_key": KEY.findall(html)[0],
            "lang": "cs",
            **answers,
        }
        client.questions = QUESTION.findall(html) if CHECKING.search(html) else []
        found = PHOTO.findall(html)
        client.photo_field = found[0] if found else ""
    except (AssertionError, IndexError, *NETWORK) as error:
        client.error = f"start: {error!r}"
    _wait(after_start, client)
    if not client.error:
        try:
            for question in client.questions:  # the page script sends the form urlencoded
                body = {"check_question": question, **client.fields}
                status, _html = post(
                    base, client.path.replace("/submit", "/check"), *form(body), context
                )
                client.checks.append(status)
        except NETWORK as error:
            client.error = f"check: {error!r}"
    _wait(after_checks, client)
    if client.error:
        return
    try:
        began = time.perf_counter()
        client.sent_at = time.time()
        client.submit, client.page = post(base, client.path, *_submission(client, jpeg), context)
        client.seconds = time.perf_counter() - began
        client.answered_at = time.time()
    except NETWORK as error:
        client.error = f"submit: {error!r}"


def _unsigned(page: str) -> str:
    return SIGNED.sub("/v/-", page)


def _statuses(values: list[int]) -> str:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(f"{status}: {count}" for status, count in sorted(counts.items()))


def _photo_bytes(args: argparse.Namespace) -> tuple[bytes, str]:
    if args.photo_file:
        return Path(args.photo_file).read_bytes(), f"file {args.photo_file}"
    return photo(args.photo_kb), "padded tiny picture (the upload is real, the decoding is not)"


def load(args: argparse.Namespace) -> tuple[list[tuple[bool | None, str]], list[str]]:
    context = _context(args.base)
    jpeg, kind = _photo_bytes(args)
    clients = [Client(number) for number in range(args.clients)]
    barriers = (threading.Barrier(args.clients), threading.Barrier(args.clients))
    threads = [
        threading.Thread(
            target=_play, args=(client, args.base, args.run, context, jpeg, barriers), daemon=True
        )
        for client in clients
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + TOTAL_SECONDS
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    results: list[tuple[bool | None, str]] = []
    if any(c.photo_field for c in clients):
        results.append((None, f"photo sent: {len(jpeg)} bytes, {kind}"))
    else:
        results.append((None, "the form has no photo field: no photo sent"))
    errors = [f"client {c.number} {c.error}" for c in clients if c.error]
    hung = sum(thread.is_alive() for thread in threads)
    if hung:
        errors.append(f"{hung} clients did not finish within {TOTAL_SECONDS:.0f} s")
    starts = [c.start for c in clients]
    checks = [status for c in clients for status in c.checks]
    submits = [c.submit for c in clients]

    def ok(statuses: list[int], expected: int) -> bool:
        return len(statuses) == expected and all(200 <= status < 300 for status in statuses)

    results.append((ok(starts, args.clients), f"starts answer 2xx ({_statuses(starts)})"))
    expected_checks = sum(len(c.questions) for c in clients)
    if expected_checks:
        results.append((ok(checks, expected_checks), f"checks answer 2xx ({_statuses(checks)})"))
    else:
        results.append((None, "no checks sent: the page does not reveal after each question"))
    with_photo = "with a photo " if any(c.photo_field for c in clients) else ""
    results.append(
        (ok(submits, args.clients), f"submits {with_photo}answer 2xx ({_statuses(submits)})")
    )
    slowest = max((c.seconds for c in clients), default=0.0)
    results.append(
        (
            0.0 < slowest < LIMIT_SECONDS,
            f"slowest submit {slowest:.2f} s, under {LIMIT_SECONDS:.0f} s",
        )
    )
    sent = [c.sent_at for c in clients if c.sent_at]
    answered = [c.answered_at for c in clients if c.answered_at]
    extra = [f"WINDOW first={min(sent):.3f} last={max(answered):.3f}"] if sent and answered else []
    # The same submission sent again, as after a lost answer: the same outcome.
    same = 0
    repeated = [c for c in clients if c.submit == 200][:REPEATING]
    for client in repeated:
        try:
            status, page = post(args.base, client.path, *_submission(client, jpeg), context)
        except NETWORK as error:
            errors.append(f"client {client.number} repeat: {error!r}")
            continue
        same += status == 200 and _unsigned(page) == _unsigned(client.page)
    results.append(
        (
            len(repeated) == REPEATING and same == REPEATING,
            f"{same}/{len(repeated)} repeated submits return the same outcome",
        )
    )
    for message in errors[:5]:
        results.append((False, message))
    return results, extra


# What to look at when the probe fails. Printed with the failure, one line each.
PROBE_HINTS = (
    "check: the proxy must send the real client address (X-Forwarded-For in deploy/Caddyfile)",
    "check: Docker's userland proxy or rootless Docker can make every client one address",
    "check: starts sent over more than 60 s let the sliding window expire (a false FAIL)",
)


def _statuses_of(counts: dict[int, int]) -> str:
    return ", ".join(f"{count} x {status}" for status, count in sorted(counts.items()))


def probe(args: argparse.Namespace) -> tuple[list[tuple[bool | None, str]], list[str]]:
    """Starts from the given address until refused, then one start from each loopback address."""
    context = _context(args.base)
    path = f"/r/{args.run}/start"
    body, content_type = form({"lang": "cs"})
    lan = Source(address=args.probe_from, bind=args.probe_from)
    statuses: dict[int, int] = {}
    refused_at = 0
    began = time.monotonic()
    while sum(statuses.values()) < args.probe_limit + 2:
        status, _html = post(args.base, path, body, content_type, context, lan)
        statuses[status] = statuses.get(status, 0) + 1
        if status != 200:
            refused_at = sum(statuses.values()) if status == 429 else 0
            break
    elapsed = time.monotonic() - began
    accepted = statuses.get(200, 0)
    refusals = {status: count for status, count in statuses.items() if status != 200}
    seen = f"{accepted} starts accepted, then {_statuses_of(refusals) or 'no refusal'}"
    loopback = {}
    for address in LOOPBACK:
        status, _html = post(
            args.base, path, body, content_type, context, Source(address=address, bind=address)
        )
        loopback[address] = status
    prefix = f"address probe: {args.probe_from} ({elapsed:.1f} s)"
    others = ", ".join(f"{a} answers {s}" for a, s in loopback.items())
    expected = args.probe_limit
    if refused_at == expected + 1 and all(s == 200 for s in loopback.values()):
        line = (
            f"{prefix}: counted apart from the loopback traffic: {seen} (429 at start "
            f"{refused_at}); loopback still answers 200 ({others})"
        )
        results: list[tuple[bool | None, str]] = [(True, line)]
    else:
        if not refused_at:
            reason = f"never refused or answered another status ({seen})"
        elif refused_at != expected + 1:
            reason = f"refused at start {refused_at}, expected {expected + 1} ({seen})"
        else:
            reason = f"loopback sources were refused too ({others})"
        results = [(False, f"{prefix}: {reason}")]
        results += [(None, hint) for hint in PROBE_HINTS]
    results.append(
        (None, "loopback sources 127.0.0.1 and 127.0.0.2 are not told apart by this probe")
    )
    return results, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--photo-kb", type=int, default=700)
    parser.add_argument("--photo-file", default="")
    parser.add_argument("--probe-from", default="")
    parser.add_argument("--probe-limit", type=int, default=300)
    args = parser.parse_args(argv)
    if args.clients < 1 or args.photo_kb < 1 or args.probe_limit < 1:
        parser.error("--clients, --photo-kb and --probe-limit must be positive")
    if args.photo_file and not Path(args.photo_file).is_file():
        parser.error(f"--photo-file {args.photo_file}: no such file")
    results, extra = probe(args) if args.probe_from else load(args)
    for passed, text in results:
        print(f"{'INFO' if passed is None else 'PASS' if passed else 'FAIL'} {text}")
    for line in extra:
        print(line)
    return 0 if all(passed is not False for passed, _text in results) else 1


if __name__ == "__main__":
    sys.exit(main())
