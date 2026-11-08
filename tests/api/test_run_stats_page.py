"""AC-84: statistics on the run page and a comparison of runs on the quiz's runs tab."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import authoring
from app.domain.models import Attempt, AttemptAnswer
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def submitted(run, score, points=None):
    found = Attempt.objects.create(
        run=run,
        revision=run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=datetime(2030, 1, 1, 10, 0, tzinfo=UTC),
        score=Decimal(score),
        max_score=run.current_revision.max_score,
    )
    if points is not None:
        question_id = run.current_revision.snapshot_json["questions"][0]["id"]
        AttemptAnswer.objects.create(
            attempt=found, question_id=question_id, answer_json={}, auto_points=Decimal(points)
        )
    return found


def test_run_page_shows_statistics(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID, data={"profile": "answers"})
    submitted(run, 1, 1)
    submitted(run, 0, 0)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Statistics" in html
    assert "Median" in html and "0.5" in html
    assert "<meter" in html
    assert "Otázka cs" in html and "50 %" in html


def test_score_profile_says_answers_are_needed(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    submitted(run, 1)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Numbers per question need a data profile that keeps all answers." in html


def test_runs_tab_shows_comparison(logged_in):
    quiz = published_quiz()
    first = authoring.open_run(quiz, admin_id=ADMIN_ID)
    submitted(first, 1)
    authoring.close_run(first, admin_id=ADMIN_ID)
    second = authoring.open_run(quiz, admin_id=ADMIN_ID)
    submitted(second, 0)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs?lang=en"))
    assert "Comparison of runs" in html
    assert "100 %" in html and "0 %" in html
