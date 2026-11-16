"""Starting and submitting are limited per address (ADR-0030); checking and resuming are not."""

import re
import uuid

import pytest

from app.api import rate_limit
from app.domain import authoring
from app.domain.models import Participant
from tests.domain.helpers import ADMIN_ID, OPTION_A, open_quiz_run, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}
REFUSED = "Too many requests from this address. Please try again in a minute."
REFUSED_CS = "Příliš mnoho požadavků z této adresy. Zkuste to prosím za minutu."
REFUSED_UK = "Забагато запитів з цієї адреси. Спробуйте ще раз за хвилину."


@pytest.fixture(autouse=True)
def fresh_limiter(settings):
    settings.KVZ_STARTS_PER_MINUTE = 300
    settings.KVZ_SUBMITS_PER_MINUTE = 120
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture
def run():
    return open_quiz_run(locales=("cs", "en", "uk"))


def ip(address="10.0.0.1"):
    return {"HTTP_X_FORWARDED_FOR": address}


def start(client, run, address="10.0.0.1", headers=None, query="", lang="cs"):
    return client.post(
        f"/r/{run.id}/start{query}",
        {"lang": lang},
        headers=headers or {},
        **ip(address),
    )


def form_of(response):
    html = response.content.decode()
    field = lambda name: re.search(rf'name="{name}" value="([^"]*)"', html).group(1)  # noqa: E731
    action = re.search(r'action="(/a/[^"]+/submit[^"]*)"', html).group(1)
    return action, {
        "attempt_token": field("attempt_token"),
        "submission_key": field("submission_key"),
        "lang": field("lang"),
    }


def answers_of(run):
    ids = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    return {f"{qid}:options[]": OPTION_A for qid in ids}


def test_start_is_refused_after_the_limit_without_creating_a_participant(settings):
    """AC-130: a start over the limit is refused with 429 and creates no participant."""
    settings.KVZ_STARTS_PER_MINUTE = 3
    run = authoring.open_run(
        published_quiz(), admin_id=ADMIN_ID, rules={"repeat_attempts": "forbid"}
    )
    for _ in range(3):  # a fresh browser each time, so each start makes a participant
        assert start(FormClient(), run).status_code == 200
    assert Participant.objects.count() == 3
    refused = start(FormClient(), run)
    assert refused.status_code == 429
    assert refused["Retry-After"] == "60"
    assert "Set-Cookie" not in refused
    assert not refused.cookies
    assert Participant.objects.count() == 3


def test_submit_is_refused_after_the_limit(client, run, settings):
    """AC-130: a submit over the limit is refused with 429 and Retry-After."""
    settings.KVZ_SUBMITS_PER_MINUTE = 2
    action, fields = form_of(start(client, run))
    body = fields | answers_of(run)
    for _ in range(2):
        assert client.post(action, body, headers=HTMX, **ip()).status_code == 200
    refused = client.post(action, body, headers=HTMX, **ip())
    assert refused.status_code == 429
    assert refused["Retry-After"] == "60"
    assert REFUSED_CS in refused.content.decode()


def test_the_limit_counts_every_request_not_only_failures(client, settings):
    settings.KVZ_STARTS_PER_MINUTE = 2
    for _ in range(2):
        assert client.post(f"/r/{uuid.uuid4()}/start", {}, **ip()).status_code == 404
    assert client.post(f"/r/{uuid.uuid4()}/start", {}, **ip()).status_code == 429


@pytest.mark.parametrize("what", ["submit", "start"])
def test_the_refusal_comes_before_any_lookup(client, settings, what):
    """The refused page still reads branding and the menu (queries), but never the id in the URL."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    settings.KVZ_SUBMITS_PER_MINUTE = 1
    settings.KVZ_STARTS_PER_MINUTE = 1
    wanted = uuid.uuid4()
    path = f"/a/{wanted}/submit" if what == "submit" else f"/r/{wanted}/start"
    assert client.post(path, {}, **ip()).status_code == 404
    with CaptureQueriesContext(connection) as queries:
        refused = client.post(path, {}, **ip())

    assert refused.status_code == 429
    statements = [query["sql"] for query in queries.captured_queries]
    assert not [sql for sql in statements if wanted.hex in sql or str(wanted) in sql]
    assert not [sql for sql in statements if '"attempt"' in sql or '"participant"' in sql]


def test_50_clients_behind_one_address_start_and_submit_at_defaults(run):
    """AC-130: 50 clients behind one address start and submit at the default limits."""
    statuses = []
    for _ in range(50):
        client = FormClient()
        started = start(client, run, "203.0.113.7", HTMX)
        statuses.append(started.status_code)
        action, fields = form_of(started)
        done = client.post(action, fields | answers_of(run), headers=HTMX, **ip("203.0.113.7"))
        statuses.append(done.status_code)
    assert statuses == [200] * 100


def test_another_address_is_not_affected(client, run, settings):
    """AC-130: a limit counts per address."""
    settings.KVZ_STARTS_PER_MINUTE = 1
    assert start(client, run, "10.0.0.1").status_code == 200
    assert start(client, run, "10.0.0.1").status_code == 429
    assert start(client, run, "10.0.0.2").status_code == 200


def test_the_refusal_is_a_fragment_for_htmx_and_a_page_otherwise(client, run, settings):
    settings.KVZ_STARTS_PER_MINUTE = 1
    start(client, run)
    fragment = start(client, run, headers=HTMX)
    assert fragment.status_code == 429
    assert fragment["HX-Retarget"] == "#play-message"
    assert "<html" not in fragment.content.decode()
    assert REFUSED_CS in fragment.content.decode()
    whole = start(client, run)
    assert whole.status_code == 429
    assert "<html" in whole.content.decode()
    assert REFUSED_CS in whole.content.decode()


@pytest.mark.parametrize(
    ("lang", "text"), [("cs", REFUSED_CS), ("en", REFUSED), ("uk", REFUSED_UK)]
)
def test_the_refusal_is_translated_in_cs_en_uk(client, run, settings, lang, text):
    """AC-141: a refusal of the start is translated."""
    settings.KVZ_STARTS_PER_MINUTE = 1
    start(client, run)
    refused = start(client, run, headers=HTMX, query=f"?lang={lang}")
    assert refused.status_code == 429
    assert text in refused.content.decode()


def test_check_and_resume_and_time_are_not_limited(client, run, settings):
    settings.KVZ_STARTS_PER_MINUTE = 1
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    action, fields = form_of(start(client, run))
    attempt_id = action.split("/")[2]
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    for _ in range(200):
        checked = client.post(
            f"/a/{attempt_id}/check",
            fields | {"check_question": question_id},
            headers=HTMX,
            **ip(),
        )
        resumed = client.post(
            f"/r/{run.id}/resume",
            {"lang": "cs", "attempt_id": attempt_id, "attempt_token": fields["attempt_token"]},
            headers=HTMX,
            **ip(),
        )
        timed = client.post(
            f"/a/{attempt_id}/time", {"attempt_token": fields["attempt_token"]}, **ip()
        )
        polled = client.get(f"/a/{attempt_id}/revision-status", **ip())
        assert 429 not in (
            checked.status_code,
            resumed.status_code,
            timed.status_code,
            polled.status_code,
        )


def quiz_page(client, run, lang):
    return client.get(f"/q/{run.quiz.slug}?lang={lang}").content.decode()


@pytest.mark.parametrize("lang", ["cs", "en", "uk"])
def test_the_start_form_carries_its_language(client, run, lang):
    """AC-141, TD-084: the start form posts to an address that names the page's language."""
    html = quiz_page(client, run, lang)
    address = f"/r/{run.id}/start?lang={lang}"
    assert f'action="{address}"' in html
    assert f'hx-post="{address}"' in html
    assert start(client, run, query=f"?lang={lang}").status_code == 200


@pytest.mark.parametrize("lang", ["cs", "en", "uk"])
def test_the_submit_form_carries_its_language(client, run, lang):
    """AC-141, TD-084: the submit form posts to an address that names the page's language."""
    started = start(client, run, lang=lang).content.decode()
    action = re.search(r'action="(/a/[^"?]+/submit)\?lang=([a-z]+)"', started)
    assert action is not None
    assert action.group(2) == lang
    assert f'hx-post="{action.group(1)}?lang={lang}"' in started


def test_a_429_on_submit_is_in_the_forms_language(client, run, settings):
    """AC-141, TD-084: a refusal answers in the language in the address, not in the browser's."""
    settings.KVZ_SUBMITS_PER_MINUTE = 1
    action, fields = form_of(start(client, run, lang="uk"))
    body = fields | answers_of(run)
    assert client.post(action, body, headers=HTMX, **ip()).status_code == 200
    refused = client.post(action, body, headers=HTMX | {"Accept-Language": "cs"}, **ip())
    assert refused.status_code == 429
    assert REFUSED_UK in refused.content.decode()
    assert REFUSED_CS not in refused.content.decode()
