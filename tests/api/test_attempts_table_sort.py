"""AC-85: the attempts table of a run sorts by a column header, without JavaScript."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain import authoring, participants
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def text(response):
    return response.content.decode()


def a_run(profile="score"):
    return authoring.open_run(
        published_quiz(questions=10), admin_id=ADMIN_ID, data={"profile": profile}
    )


def played(run, name, score, minute, duration=None):
    who = Participant.objects.create(
        run=run, anonymous_key_hash=f"h{Participant.objects.count()}", display_name=name
    )
    Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=run.current_revision.max_score,
        duration_ms=duration,
    )


def names(run, **query):
    return [row.name for row in participants.attempt_rows(run, **query)]


def three(run):
    played(run, "bára", 5, 0, 9000)
    played(run, "", 9, 1, 3000)
    played(run, "Adam", 2, 2, None)


def test_sort_by_score_desc():
    run = a_run()
    three(run)
    assert names(run, sort="score", descending=True) == ["", "bára", "Adam"]
    assert names(run, sort="score") == ["Adam", "bára", ""]


def test_sort_by_name_empty_last():
    run = a_run()
    three(run)
    assert names(run, sort="name") == ["Adam", "bára", ""]
    assert names(run, sort="name", descending=True) == ["bára", "Adam", ""]


def test_unknown_sort_falls_back():
    run = a_run()
    three(run)
    assert names(run, sort="email") == ["bára", "", "Adam"]


def test_sort_by_duration_missing_last():
    run = a_run("detailed")
    three(run)
    assert names(run, sort="duration") == ["", "bára", "Adam"]


def test_duration_column_only_when_stored(logged_in):
    run = a_run()
    played(run, "Ema", 1, 0)
    assert "Duration" not in text(logged_in.get(f"/admin/runs/{run.id}/attempts?lang=en"))
    detailed = authoring.open_run(
        published_quiz("jiny"), admin_id=ADMIN_ID, data={"profile": "detailed"}
    )
    played(detailed, "Ema", 1, 0, 65000)
    html = text(logged_in.get(f"/admin/runs/{detailed.id}/attempts?lang=en"))
    assert "Duration" in html and "1:05" in html


def test_header_links_flip_direction(logged_in):
    run = a_run()
    three(run)
    html = text(logged_in.get(f"/admin/runs/{run.id}/attempts?lang=en&sort=score&dir=desc"))
    assert 'aria-sort="descending"' in html
    assert "sort=score&amp;dir=asc" in html
    assert "sort=name&amp;dir=asc" in html
    rows = re.findall(r"<tr data-attempt-row>.*?</tr>", html, re.S)
    assert "9 / 10" in rows[0] and "2 / 10" in rows[-1]
