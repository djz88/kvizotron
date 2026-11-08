"""AC-70, AC-81, AC-83: the public scoreboard page, its refresh, the projector and own place."""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.cache import cache

from app.contracts import SCOREBOARD_LIVE_NAMES, SCOREBOARD_VISIBILITY
from app.domain import authoring, participants, results, run_links
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}")


def a_run(quiz=None, **chosen):
    values = {SCOREBOARD_VISIBILITY: "live"} | chosen
    return authoring.open_run(quiz or published_quiz(), admin_id=ADMIN_ID, results=values)


def url(run, rest=""):
    return f"/q/{run.quiz.slug}/r/{run.id}/scoreboard{rest}"


def text(response):
    return response.content.decode()


def played(run, name="", email=None, score=1, key=None):
    who = Participant.objects.create(
        run=run,
        anonymous_key_hash=participants.key_hash(run, key)
        if key
        else f"h{Participant.objects.count()}",
        display_name=name,
        email=email,
    )
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=Attempt.Status.SUBMITTED,
        submitted_at=datetime(2030, 1, 1, 10, Participant.objects.count(), tzinfo=UTC),
        score=Decimal(score),
        max_score=run.current_revision.max_score,
    )


def start(client, run):
    return client.post(f"/r/{run.id}/start", {"lang": "cs"})


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def submit_correct(client, run, response):
    html = text(response)
    attempt_id = html.split("/a/")[1].split("/")[0]
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    return client.post(
        f"/a/{attempt_id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": "cs",
            f"{question_id}:options[]": OPTION_A,
        },
    )


def test_hidden_board_says_so(client):
    run = a_run(**{SCOREBOARD_VISIBILITY: "hidden"})
    response = client.get(url(run) + "?lang=en")
    assert response.status_code == 200
    assert "Žebříček není veřejný." in text(response)


def test_live_board_lists_rows_without_email_or_ids(client):
    run = a_run()
    attempt = played(run, "Ema", email="ema@example.cz")
    html = text(client.get(url(run)))
    assert "Ema" in html
    assert "ema@example.cz" not in html
    for secret in (str(attempt.id), str(attempt.participant_id), attempt.id.hex):
        assert secret not in html
    assert not [found for found in UUID.findall(html) if found.replace("-", "") != run.id.hex]


def test_projector_view_has_rank_name_score_only(client):
    run = a_run(scoreboard_show_time="on")
    played(run, "Ema")
    html = text(client.get(url(run, "?view=projector&lang=en")))
    assert "projector" in html and "Ema" in html
    assert "Submitted" not in html and "%" not in html


def test_fragment_polls_while_open_and_stops_when_final(client):
    run = a_run()
    played(run, "Ema")
    assert 'hx-trigger="every 15s"' in text(client.get(url(run, "/rows")))
    authoring.close_run(run, admin_id=ADMIN_ID)
    cache.clear()  # the public board is cached for a few seconds
    html = text(client.get(url(run, "/rows")))
    assert "hx-trigger" not in html and "Ema" in html


def test_switching_to_hidden_shows_reason_and_keeps_polling(client):
    run = a_run()
    played(run, "Ema")
    client.get(url(run, "/rows"))
    results.set_display(run, {SCOREBOARD_VISIBILITY: "after_end"}, admin_id=ADMIN_ID)
    cache.clear()
    html = text(client.get(url(run, "/rows?lang=en")))
    assert "Žebříček se ukáže po skončení běhu." in html
    assert 'hx-trigger="every 15s"' in html and "Ema" not in html


def test_pending_grading_says_why(client):
    run = a_run()
    played(run, "Ema")
    Attempt.objects.update(status=Attempt.Status.PENDING_GRADING)
    assert "Žebříček se ukáže, až budou ohodnocené všechny odpovědi." in text(
        client.get(url(run, "?lang=en"))
    )


def test_own_row_marked_from_cookie_not_name():
    run = a_run(**{SCOREBOARD_LIVE_NAMES: "shown"})
    played(run, "Ema", key="my-browser-key")
    played(run, "Ema")
    browser = FormClient()
    browser.cookies[participants.cookie_name(run)] = "my-browser-key"
    html = text(browser.get(url(run, "?lang=en")))
    assert html.count("data-mine") == 1
    assert text(FormClient().get(url(run))).count("data-mine") == 0


def test_test_run_board_is_404(client):
    quiz = published_quiz()
    link = run_links.create(quiz, quiz.revisions.get(), expires_at=None, admin_id=ADMIN_ID)
    assert client.get(url(link.run)).status_code == 404
    run = a_run(published_quiz("jiny"))
    assert client.get(f"/q/kviz/r/{run.id}/scoreboard").status_code == 404


def test_visible_board_sets_cookie_even_when_repeating_allowed():
    run = a_run()
    response = start(FormClient(), run)
    assert participants.cookie_name(run) in response.cookies
    assert Attempt.objects.get().participant is not None


def test_hidden_board_with_repeating_allowed_sets_no_cookie():
    run = a_run(**{SCOREBOARD_VISIBILITY: "hidden"})
    response = start(FormClient(), run)
    assert participants.cookie_name(run) not in response.cookies
    assert Participant.objects.count() == 0


def test_same_browser_three_times_is_one_row():
    run = a_run()
    browser = FormClient()
    for _ in range(3):
        submit_correct(browser, run, start(browser, run))
    board = results.board(run, audience="admin", locale="cs")
    assert len(board.tables[0].rows) == 1


def test_result_shows_place():
    run = a_run()
    played(run, "Ema", score=1)
    browser = FormClient()
    html = text(submit_correct(browser, run, start(browser, run)))
    assert "1. z 2" in html
    assert url(run) in html


def test_quiz_page_links_public_board(client):
    run = a_run()
    assert url(run) in text(client.get(f"/q/{run.quiz.slug}"))
    authoring.close_run(run, admin_id=ADMIN_ID)
    assert url(run) in text(client.get(f"/q/{run.quiz.slug}"))
    hidden = a_run(published_quiz("jiny"), **{SCOREBOARD_VISIBILITY: "hidden"})
    assert "/scoreboard" not in text(client.get(f"/q/{hidden.quiz.slug}")).replace(
        "/assets/scoreboard.js", ""
    )


def test_label_html_is_escaped(client):
    quiz = published_quiz()
    quiz.anonymous_label = {"cs": "<b>Tým</b> NN"}
    quiz.save()
    run = a_run(quiz)
    played(run, "")
    html = text(client.get(url(run)))
    assert "<b>Tým</b>" not in html and "&lt;b&gt;Tým&lt;/b&gt; 1" in html


def test_ukrainian_board(client):
    run = a_run(published_quiz(locales=("cs", "uk")))
    played(run, "")
    html = text(client.get(url(run, "?lang=uk")))
    assert "Гравець 1" in html


def test_table_stacks_on_a_phone(client):
    # Found in the browser: five columns overflowed a 390 px screen.
    run = a_run(scoreboard_show_time="on")
    played(run, "Ema")
    assert '<table class="stack">' in text(client.get(url(run)))
