"""AC-15: fifty participants submit at once from one address, with photos, on a real database.

The in-memory test database cannot show WAL, `IMMEDIATE` transactions or the busy timeout, so
this runs the production server command (`gunicorn`, one worker, eight threads) on a migrated
SQLite file in WAL and talks to it over the loopback address with the standard library.
"""

import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid

from PIL import Image

from tests.support.run import run_manage
from tests.support.server import LOG_NAME, running_server

CLIENTS = 50
REPEATING = 5
SLOWEST_SECONDS = 15.0
REQUEST_SECONDS = 30
JOIN_SECONDS = 45.0
TOLERANCE = 12  # of a colour channel, after the lossy JPEG and WebP

SEED = """
import json
from app.domain import authoring
from app.domain.models import Quiz
from app.kernel.models import AdminUser
quiz = Quiz.objects.create(slug="load", title={"cs": "Zátěž"}, description={"cs": "Zátěž"},
                           default_locale="cs", supported_locales=["cs"])
choice = authoring.save_question(quiz, None, "choice", {
    "prompt": {"cs": "Otázka"},
    "options": [{"id": "aaaa1111", "text": {"cs": "A"}}, {"id": "bbbb2222", "text": {"cs": "B"}}],
    "correct": ["bbbb2222"],
})
photo = authoring.save_question(quiz, None, "image_answer", {
    "prompt": {"cs": "Vyfoťte"}, "auto": {"right": 2, "total": 10}}, points=10, scoring="partial")
admin = str(AdminUser.objects.create_admin("seed-admin", "Seed-only-password-1").pk)
authoring.publish(quiz, admin_id=admin)
run = authoring.open_run(quiz, admin_id=admin, data={"profile": "answers"})
print(json.dumps({"run": str(run.id), "choice": choice, "photo": photo}))
"""

TOKEN = re.compile(r'name="attempt_token" value="([^"]+)"')
KEY = re.compile(r'name="submission_key" value="([^"]+)"')
SIGNED = re.compile(r"/v/[\w:-]+")
ATTEMPT = re.compile(r"/a/([0-9a-f-]{36})/submit")


def _colour(number: int) -> tuple[int, int, int]:
    """A colour of its own for each client, far enough from the others to survive compression."""
    return (number % 8 * 32, number // 8 % 8 * 32, 128)


def _jpeg(number: int) -> bytes:
    """A small valid photo, one solid colour that tells which client sent it."""
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), _colour(number)).save(buffer, "JPEG")
    return buffer.getvalue()


def _choice(number: int) -> str:
    """The two options alternate, so a swapped answer shows."""
    return ("bbbb2222", "aaaa1111")[number % 2]


def _multipart(fields: dict[str, str], files: dict[str, bytes]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    for name, data in files.items():
        body += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="foto.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'
            ).encode()
            + data
            + b"\r\n"
        )
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, content_type: str) -> tuple[int, str]:
    request = urllib.request.Request(  # noqa: S310  # loopback address of the test server
        url, data=body, method="POST", headers={"Content-Type": content_type}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_SECONDS) as response:  # noqa: S310
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def _unsigned(page: str) -> str:
    return SIGNED.sub("/v/-", page)


def _seed(db) -> dict[str, str]:
    result = run_manage("shell", "-v", "0", "-c", SEED, db=db)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _count(file_db, sql: str, *parameters: object) -> int:
    return int(file_db.execute(sql, *parameters)[0][0])


def _normal(identifier: object) -> str:
    return str(identifier).replace("-", "")


def _snapshot(file_db, run_key: str) -> dict[str, object]:
    """Everything the database holds about the run's attempts, to compare before and after."""
    attempts = file_db.execute(
        "select id, status, score, submission_key, submitted_at from attempt where run_id = ? "
        "order by id",
        run_key,
    )
    answers = file_db.execute(
        "select attempt_id, question_id, answer_json, asset_id from attempt_answer "
        "where attempt_id in (select id from attempt where run_id = ?) "
        "order by attempt_id, question_id",
        run_key,
    )
    assets = file_db.execute("select id, storage_key from media_asset order by id")
    return {"attempts": attempts, "answers": answers, "assets": assets}


def _stored_by_attempt(file_db, run_key: str, seeded: dict[str, str], media) -> dict[str, tuple]:
    """For each attempt: the stored choice answer and the colour of the stored photo."""
    keys = dict(file_db.execute("select id, storage_key from media_asset"))
    stored: dict[str, tuple] = {}
    rows = file_db.execute(
        "select attempt_id, question_id, answer_json, asset_id from attempt_answer "
        "where attempt_id in (select id from attempt where run_id = ?)",
        run_key,
    )
    for attempt_id, question_id, answer_json, asset_id in rows:
        entry = stored.setdefault(_normal(attempt_id), [None, None])
        if question_id == seeded["choice"]:
            entry[0] = json.loads(answer_json)["options"]
        if question_id == seeded["photo"]:
            with Image.open(media / keys[_normal(asset_id)]) as image:
                entry[1] = image.convert("RGB").resize((1, 1)).getpixel((0, 0))
    return {attempt: tuple(entry) for attempt, entry in stored.items()}


def _near(found: tuple[int, int, int], expected: tuple[int, int, int]) -> bool:
    return all(abs(a - b) <= TOLERANCE for a, b in zip(found, expected, strict=True))


def test_50_participants_submit_at_once_with_photos(file_db, tmp_path):
    """AC-15, AC-139: 50 submissions at once, no lost result, no duplicate, no lock, no 429."""
    seeded = _seed(file_db.path)
    run = seeded["run"]
    photo_field = f"{seeded['photo']}:image"
    media = tmp_path / "media"
    barrier = threading.Barrier(CLIENTS)
    outcomes: list[dict] = [{} for _ in range(CLIENTS)]
    errors: list[BaseException] = []

    def participant(number: int, base: str) -> None:
        try:
            outcome = outcomes[number]
            barrier.wait(timeout=REQUEST_SECONDS)
            status, html = _post(
                f"{base}/r/{run}/start", b"lang=cs", "application/x-www-form-urlencoded"
            )
            outcome["start"] = status
            if status != 200:
                raise AssertionError(f"client {number}: start answered {status}")
            attempt = ATTEMPT.findall(html)[0]
            fields = {
                "attempt_token": TOKEN.findall(html)[0],
                "submission_key": KEY.findall(html)[0],
                "lang": "cs",
                f"{seeded['choice']}:options[]": _choice(number),
            }
            outcome["fields"], outcome["attempt"] = fields, attempt
            body, content_type = _multipart(fields, {photo_field: _jpeg(number)})
            began = time.perf_counter()
            status, page = _post(f"{base}/a/{attempt}/submit", body, content_type)
            outcome["submit"], outcome["page"] = status, page
            outcome["seconds"] = time.perf_counter() - began
        except BaseException as error:  # noqa: BLE001  # reported by the main thread
            errors.append(error)
            barrier.abort()

    run_key = run.replace("-", "")  # the way SQLite keeps a UUID
    with running_server(file_db.path, media) as base:
        threads = [
            threading.Thread(target=participant, args=(n, base), daemon=True)
            for n in range(CLIENTS)
        ]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + JOIN_SECONDS
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        server_log = (file_db.path.parent / LOG_NAME).read_text(errors="replace")
        assert not any(thread.is_alive() for thread in threads), f"hung clients\n{server_log}"
        assert not errors, f"{errors[:3]}\n{server_log}"

        before = _snapshot(file_db, run_key)
        # The same submission sent again by some of them: the same result, nothing new.
        repeats = []
        for outcome in outcomes[:REPEATING]:
            body, content_type = _multipart(outcome["fields"], {photo_field: _jpeg(49)})
            repeats.append(_post(f"{base}/a/{outcome['attempt']}/submit", body, content_type))

    server_log = (file_db.path.parent / LOG_NAME).read_text(errors="replace")
    assert [o["start"] for o in outcomes] == [200] * CLIENTS, server_log
    assert [o["submit"] for o in outcomes] == [200] * CLIENTS, server_log
    assert "database is locked" not in server_log and "OperationalError" not in server_log
    assert "Traceback" not in server_log, server_log
    assert max(o["seconds"] for o in outcomes) < SLOWEST_SECONDS

    total = "select count(*) from attempt where run_id = ?"
    assert _count(file_db, total, run_key) == CLIENTS
    finished = _count(file_db, f"{total} and status in ('SUBMITTED', 'PENDING_GRADING')", run_key)
    assert finished == CLIENTS
    keys = file_db.execute(
        "select count(distinct submission_key) from attempt where run_id = ?", run_key
    )
    assert keys[0][0] == CLIENTS
    # Only the signed private link differs: it carries the moment it was made.
    assert [
        (status, _unsigned(page) == _unsigned(outcomes[n]["page"]))
        for n, (status, page) in enumerate(repeats)
    ] == [(200, True)] * REPEATING
    assert _snapshot(file_db, run_key) == before, "a repeated submit changed the database"

    # What each attempt holds is what its own client sent: nothing lost, swapped or shared.
    stored = _stored_by_attempt(file_db, run_key, seeded, media)
    assert len(stored) == CLIENTS
    for number, outcome in enumerate(outcomes):
        attempt_id = _normal(outcome["attempt"])
        options, colour = stored[attempt_id]
        assert options == [_choice(number)], f"client {number} got another choice answer"
        assert _near(colour, _colour(number)), f"client {number} got another photo: {colour}"
    distinct_assets = (
        "select count(distinct asset_id) from attempt_answer "
        "where attempt_id in (select id from attempt where run_id = ?)"
    )
    assert _count(file_db, distinct_assets, run_key) == CLIENTS
    assert _count(file_db, "select count(*) from media_asset where private = 1") == CLIENTS
    assert len(list(media.rglob("*.webp"))) == CLIENTS
