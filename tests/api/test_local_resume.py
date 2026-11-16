"""AC-11, AC-80: the page asks for the kept attempt by its token, in a POST body."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.domain import access_codes, attempts, authoring
from app.domain.models import Attempt
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
DROP = "X-Kvz-Drop-Copy"


@pytest.fixture(autouse=True)
def at_nine(monkeypatch):
    freeze(monkeypatch, NOW)
    return monkeypatch


def a_run(**fields):
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, **fields)


def resume(run, started, client=None, **extra):
    return (client or FormClient()).post(
        f"/r/{run.id}/resume",
        {"lang": "cs", "attempt_id": str(started.attempt.id), "attempt_token": started.token},
        **extra,
    )


def test_resume_renders_the_same_questions_with_a_fresh_token():
    run = a_run()
    started = attempts.start(run)
    response = resume(run, started, HTTP_HX_REQUEST="true")
    text = response.content.decode()
    assert response.status_code == 200
    assert f"/a/{started.attempt.id}/submit" in text
    assert 'name="attempt_token"' in text and 'name="submission_key"' in text
    assert f'data-run="{run.id}"' in text
    assert 'data-local-resume="on"' in text
    assert "data-copy-expires=" in text
    assert DROP not in response.headers


def test_resume_needs_no_code_cookie():
    run = a_run()
    started = attempts.start(run)
    access_codes.set_code(run, "ABCD2345", admin_id=ADMIN_ID)
    run.refresh_from_db()
    assert resume(run, started, HTTP_HX_REQUEST="true").status_code == 200


def test_resume_refused_for_other_run_drops_the_copy():
    run, other = a_run(), authoring.open_run(published_quiz("jiny"), admin_id=ADMIN_ID)
    response = resume(other, attempts.start(run), HTTP_HX_REQUEST="true")
    assert response.status_code == 403 and response[DROP] == "1"


def test_resume_refused_after_submit_and_drops_copy():
    run = a_run()
    started = attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, "k" * 20)
    response = resume(run, started, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and response[DROP] == "1"


def test_resume_refused_after_limit(at_nine):
    run = a_run(limit_sec=60)
    started = attempts.start(run)
    freeze(at_nine, NOW + timedelta(minutes=5))
    response = resume(run, started, HTTP_HX_REQUEST="true")
    assert response.status_code == 410 and response[DROP] == "1"


def test_resume_refused_when_abandoned():
    run = a_run()
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.id).update(status=Attempt.Status.ABANDONED)
    assert resume(run, started, HTTP_HX_REQUEST="true")[DROP] == "1"


def test_resume_off_refused():
    run = a_run()
    started = attempts.start(run)
    Attempt.objects.filter(pk=started.attempt.id).update(
        settings_json={**started.attempt.settings_json, "local_resume": "off"}
    )
    response = resume(run, started, HTTP_HX_REQUEST="true")
    assert response.status_code == 409 and response[DROP] == "1"


def test_malformed_request_does_not_drop_the_copy():
    run = a_run()
    response = FormClient().post(
        f"/r/{run.id}/resume",
        {"lang": "cs", "attempt_id": "nope", "attempt_token": "x"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 400 and DROP not in response.headers


def test_token_never_in_url():
    run = a_run()
    started = attempts.start(run)
    text = resume(run, started, HTTP_HX_REQUEST="true").content.decode()
    fresh = re.search(r'name="attempt_token" value="([^"]+)"', text)[1]
    for match in re.finditer(r'(?:href|action|hx-[a-z]+)="([^"]*)"', text):
        assert fresh not in match[1] and started.token not in match[1]
    assert "?attempt_token" not in text


def questions_html(run, started, off=False):
    if off:
        Attempt.objects.filter(pk=started.attempt.pk).update(
            settings_json={**started.attempt.settings_json, "local_resume": "off"}
        )
    return resume(run, started, HTTP_HX_REQUEST="true").content.decode()


def test_questions_carry_resume_hooks():
    run = a_run()
    text = questions_html(run, attempts.start(run))
    assert 'data-local-resume="on"' in text
    assert "data-photo-note=" in text
    assert "data-resume-device" in text
    assert "Odpovědi se do odeslání drží v tomto prohlížeči, nejdéle 24 hodin." in text


def test_questions_have_no_resume_hooks_when_off():
    run = a_run()
    text = questions_html(run, attempts.start(run), off=True)
    assert "data-local-resume" not in text
    assert "data-resume-device" not in text


def test_quiz_page_has_hidden_continue_block():
    run = a_run()
    text = FormClient().get(f"/q/{run.quiz.slug}").content.decode()
    assert re.search(r"<div data-resume-offer[^>]* hidden>", text)
    assert "data-resume-restart" in text


@pytest.mark.parametrize(
    ("rules", "restart"),
    [
        ({"repeat_attempts": "allow"}, True),
        ({"repeat_attempts": "allow", "unfinished_attempt": "used"}, True),
        ({"repeat_attempts": "forbid", "unfinished_attempt": "used"}, False),
        ({"repeat_attempts": "forbid", "unfinished_attempt": "submitted"}, True),
        ({"repeat_attempts": "forbid", "unfinished_attempt": "continue"}, False),
    ],
)
def test_may_restart_follows_rules(rules, restart):
    run = a_run(rules=rules)
    text = FormClient().get(f"/q/{run.quiz.slug}").content.decode()
    offer = re.search(r"<div data-resume-offer[^>]*>", text).group(0)
    assert ("data-may-restart" in offer) is restart


def test_every_public_page_loads_the_script_that_sweeps_old_copies():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    for path in (f"/q/{quiz.slug}?lang=cs", "/"):
        html = FormClient().get(path).content.decode()
        assert "/resume.js" in html, path
    assert 'startsWith("kvz-attempt-")' in open("app/api/assets/resume.js").read()


def _script_pattern(name):
    """The regex literal of resume.js that ends in `name`, as a Python pattern."""
    source = open("app/api/assets/resume.js").read()
    found = re.search(rf"/(\\/[^\n]*?{name}[^/\n]*?\$)/\.", source)
    assert found, f"resume.js has no address pattern for /{name}"
    return re.compile(found.group(1).replace("\\/", "/"))


@pytest.mark.parametrize(
    ("name", "address", "matches"),
    [
        ("submit", "/a/123/submit", True),
        ("submit", "/a/123/submit?lang=cs", True),
        ("submit", "/a/123/submitx", False),
        ("submit", "/a/123/check", False),
        ("resume", "/r/0a-b/resume", True),
        ("resume", "/r/0a-b/resume?lang=uk", True),
        ("resume", "/r/0a-b/resumex", False),
        ("resume", "/r/0a-b/start", False),
    ],
)
def test_resume_script_matches_addresses_with_the_language_query(name, address, matches):
    """AC-141, TD-084: addresses ending in ?lang=... must still match resume.js."""
    pattern = _script_pattern(name)
    assert bool(pattern.search(address)) is matches, (
        f"resume.js /{name}/ pattern {pattern.pattern!r} on {address}"
    )
