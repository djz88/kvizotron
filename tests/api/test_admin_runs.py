import io
from uuid import uuid7

import pytest
import segno
from django.test import Client

from app.domain import attempts
from app.domain.models import QuizRun
from tests.domain.helpers import make_quiz, open_quiz_run, published_quiz

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def test_open_run_redirects_to_its_page(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/runs")
    run = QuizRun.objects.get()
    assert response["Location"] == f"/admin/runs/{run.id}"


def test_open_run_without_publication_shows_error(logged_in):
    response = logged_in.post(f"/admin/quizzes/{make_quiz().id}/runs")
    assert response.status_code == 200
    assert "Nejdřív kvíz publikujte." in text(response)
    assert not QuizRun.objects.exists()


def test_open_second_run_shows_error(logged_in):
    run = open_quiz_run()
    response = logged_in.post(f"/admin/quizzes/{run.quiz_id}/runs")
    assert "Tento kvíz už má otevřené kolo." in text(response)
    assert QuizRun.objects.count() == 1


def test_run_page_shows_public_url_qr_and_submitted_count(logged_in):
    run = open_quiz_run()
    started = attempts.start(run)
    attempts.start(run)
    attempts.submit(started.attempt.id, started.token, {}, "key-00000001")
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert "http://testserver/q/kviz" in html
    assert f'src="/admin/quizzes/{run.quiz_id}/qr.svg"' in html
    assert "Odesláno pokusů: 1" in html


def test_unknown_run_is_404(logged_in):
    assert logged_in.get(f"/admin/runs/{uuid7()}").status_code == 404


def test_close_run_stops_public_start(logged_in, client):
    run = open_quiz_run()
    assert logged_in.get(f"/admin/runs/{run.id}/close").status_code == 405
    assert logged_in.post(f"/admin/runs/{run.id}/close")["Location"] == f"/admin/runs/{run.id}"
    assert Client().post(f"/r/{run.id}/start").status_code == 409
    assert "Uzavřené" in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_close_without_csrf_token_is_403(admin_user):
    run = open_quiz_run()
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    assert client.post(f"/admin/runs/{run.id}/close").status_code == 403


def test_qr_encodes_absolute_public_url(logged_in):
    quiz = make_quiz("kviz")
    buffer = io.BytesIO()
    segno.make("http://testserver/q/kviz", error="m").save(buffer, kind="svg", scale=4, border=2)
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/qr.svg").content == buffer.getvalue()


def test_qr_content_type_is_svg(logged_in):
    response = logged_in.get(f"/admin/quizzes/{make_quiz().id}/qr.svg")
    assert response["Content-Type"] == "image/svg+xml"
