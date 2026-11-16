"""AC-172 to AC-175 together: an exam with a resit, played over HTTP from start to the answers."""

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from app.domain import authoring, quiz_types
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]*)"', html).group(1)


def start(client, run):
    return client.post(
        f"/r/{run.id}/start", {"lang": "en", "participant_name": "Ema"}, headers=HTMX
    )


def submit(client, run, started):
    html = started.content.decode()
    action = re.search(r'action="(/a/[^"?]+/submit)(?:\?[^"]*)?"', html).group(1)
    fields = {name: hidden(html, name) for name in ("attempt_token", "submission_key", "lang")}
    ids = [q["id"] for q in run.current_revision.snapshot_json["questions"]]
    answers = {f"{qid}:options[]": OPTION_A for qid in ids}
    return client.post(action, fields | answers | {"participant_name": "Ema"}, headers=HTMX)


def test_exam_with_a_resit_from_expired_attempt_to_the_answers():
    """AC-172, AC-173, AC-175: an expired try counts, the resit passes, no third."""
    quiz = published_quiz("zkouska", ("cs", "en", "uk"))
    quiz_types.apply(quiz, "resit_exam", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    client = FormClient()

    assert start(client, run).status_code == 200
    first = Attempt.objects.get()
    Attempt.objects.filter(pk=first.pk).update(
        started_at=timezone.now() - timedelta(minutes=31)
    )  # the 30 minutes ran out

    second = start(client, run)
    assert second.status_code == 200  # a new attempt: the expired one does not lock the browser
    assert Attempt.objects.filter(run=run).count() == 2
    result = submit(client, run, second)
    html = result.content.decode()
    assert "Passed ✓" in html
    assert "Kept score" not in html  # only one attempt was submitted
    link = re.search(r'href="(/v/[^"]+)"', html).group(1)

    third = start(client, run)
    assert third.status_code == 409
    assert "You have used all 2 attempts." in third.content.decode()
    page = client.get(f"/q/{quiz.slug}?lang=en").content.decode()
    assert "You have used all 2 attempts." in page
    assert "data-start-form" not in page
    assert "Attempts left" not in page

    authoring.close_run(run, admin_id=ADMIN_ID)
    QuizRun.objects.filter(pk=run.pk).update(closed_at=timezone.now() - timedelta(minutes=5))
    assert "reveal-correct" not in FormClient().get(link).content.decode()
    QuizRun.objects.filter(pk=run.pk).update(closed_at=timezone.now() - timedelta(minutes=11))
    assert "reveal-correct" in FormClient().get(link).content.decode()
