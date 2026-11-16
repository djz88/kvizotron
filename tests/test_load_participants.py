"""The load script builds a valid photo, and its criteria and probe can fail as well as pass.

A small server on the loopback addresses stands in for the application: it answers the start
and submit routes and counts starts per source address the way the limiter does.
"""

import io
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from tools import load_participants

START_HTML = (
    '<form action="/a/{attempt}/submit" data-flow data-flow-check>'
    '<input name="attempt_token" value="tok"><input name="submission_key" value="key-{n}">'
    '<section data-question="q1"><input type="radio" name="q1:options[]" value="b"></section>'
    '<input type="file" name="q2:image"></form>'
)


class Fake(ThreadingHTTPServer):
    """Counts starts per source address; `shared` makes every source look like one address."""

    daemon_threads = True

    def __init__(self, limit: int = 1000, shared: bool = False, submit_status: int = 200) -> None:
        super().__init__(("0.0.0.0", 0), Handler)  # noqa: S104  # loopback tests need 127.0.0.x
        self.limit, self.shared, self.submit_status = limit, shared, submit_status
        self.starts: dict[str, int] = {}
        self.lock = threading.Lock()
        self.numbers = 0
        self.submitted: list[int] = []


class Handler(BaseHTTPRequestHandler):
    server: Fake

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, text: str) -> None:
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        server = self.server
        if self.path.endswith("/start"):
            key = "all" if server.shared else self.client_address[0]
            with server.lock:
                server.starts[key] = server.starts.get(key, 0) + 1
                refused = server.starts[key] > server.limit
                server.numbers += 1
                number = server.numbers
            if refused:
                self._send(429, "slow down")
            else:
                self._send(200, START_HTML.format(attempt=f"{number:036d}", n=number))
        elif self.path.endswith("/check"):
            self._send(200, "<p>revealed</p>")
        elif self.path.endswith("/submit"):
            server.submitted.append(len(body))
            self._send(server.submit_status, "result /v/abc:123:sig")
        else:
            self._send(404, "")


@contextmanager
def serving(**options: object) -> Iterator[tuple[Fake, str]]:
    server = Fake(**options)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[str]]:
    code = load_participants.main(list(argv))
    return code, capsys.readouterr().out.splitlines()


def test_the_generated_photo_is_a_valid_jpeg_of_about_the_size_asked_for() -> None:
    for kilobytes in (1, 60, 700):
        data = load_participants.photo(kilobytes)
        assert abs(len(data) - kilobytes * 1024) < 200
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            assert image.format == "JPEG"
            assert image.size == (32, 32)


def test_the_multipart_body_carries_the_fields_and_the_file() -> None:
    body, content_type = load_participants.multipart({"a": "1"}, {"x:image": b"DATA"})
    boundary = content_type.split("boundary=")[1].encode()
    assert body.count(b"--" + boundary) == 3  # two parts and the closing line
    assert b'name="a"\r\n\r\n1' in body and b'name="x:image"; filename="foto.jpg"' in body


def test_a_load_pass_prints_one_line_per_criterion_and_the_submit_window(capsys, tmp_path) -> None:
    """AC-139: the load script reports each criterion and the window of the submissions."""
    picture = tmp_path / "photo.jpg"
    picture.write_bytes(b"\xff\xd8 my own picture \xff\xd9")
    with serving() as (server, base):
        code, lines = run(
            capsys, "--base", base, "--run", "r", "--clients", "6", "--photo-file", str(picture)
        )
    assert code == 0, lines
    assert [line.split()[0] for line in lines if not line.startswith("WINDOW")] == [
        "INFO",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
        "PASS",
    ]
    window = [line for line in lines if line.startswith("WINDOW ")]
    assert len(window) == 1
    found = re.fullmatch(r"WINDOW first=([\d.]+) last=([\d.]+)", window[0])
    assert found is not None
    first, last = float(found[1]), float(found[2])
    assert 0 < first <= last
    assert len(server.submitted) == 6 + 5  # the six submits and five repeats
    assert all(size > len(picture.read_bytes()) for size in server.submitted)


def test_a_refused_submit_is_a_failure(capsys) -> None:
    with serving(submit_status=429) as (_server, base):
        code, lines = run(capsys, "--base", base, "--run", "r", "--clients", "3")
    assert code == 1
    assert any(line.startswith("FAIL submits") for line in lines), lines


def test_a_dead_server_ends_in_fail_lines_not_a_traceback(capsys) -> None:
    code, lines = run(capsys, "--base", "http://127.0.0.1:9", "--run", "r", "--clients", "3")
    assert code == 1
    assert any(line.startswith("FAIL") for line in lines), lines


def test_a_missing_photo_file_is_refused(tmp_path) -> None:
    with pytest.raises(SystemExit):
        load_participants.main(
            ["--base", "http://x", "--run", "r", "--photo-file", str(tmp_path / "none.jpg")]
        )


def test_the_probe_passes_when_sources_are_counted_apart(capsys) -> None:
    with serving(limit=5) as (_server, base):
        code, lines = run(
            capsys,
            "--base",
            base,
            "--run",
            "r",
            "--probe-from",
            "127.0.0.3",
            "--probe-limit",
            "5",
        )
    assert code == 0, lines
    assert any(line.startswith("PASS address probe") and "127.0.0.3" in line for line in lines)
    assert any("5 starts accepted" in line and "429 at start 6" in line for line in lines)
    assert any(
        line.startswith("INFO") and "127.0.0.1 and 127.0.0.2 are not told apart" in line
        for line in lines
    )
    assert not any("counted per source address" in line for line in lines)


def test_the_probe_fails_and_says_what_to_check_when_all_sources_are_one(capsys) -> None:
    """AC-139: the address probe can fail."""
    with serving(limit=5, shared=True) as (_server, base):
        code, lines = run(
            capsys,
            "--base",
            base,
            "--run",
            "r",
            "--probe-from",
            "127.0.0.3",
            "--probe-limit",
            "5",
        )
    assert code == 1
    assert any(line.startswith("FAIL address probe") for line in lines), lines
    text = "\n".join(lines)
    assert "userland proxy" in text and "X-Forwarded-For" in text and "60 s" in text


def test_the_probe_fails_when_nothing_is_ever_refused(capsys) -> None:
    with serving(limit=1000) as (_server, base):
        code, lines = run(
            capsys,
            "--base",
            base,
            "--run",
            "r",
            "--probe-from",
            "127.0.0.3",
            "--probe-limit",
            "5",
        )
    assert code == 1
    assert any(line.startswith("FAIL address probe") and "never refused" in line for line in lines)
