"""AC-70, AC-81, AC-83: the public scoreboard page, its refresh, the projector and own place."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.cache import cache

from app.contracts import SCOREBOARD_LIVE_NAMES, SCOREBOARD_SHOW_SCORE, SCOREBOARD_VISIBILITY
from app.domain import authoring, participants, results, run_links
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, OPTION_A, add_question, published_quiz
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


def test_projector_view_has_rank_name_score_only(logged_in):
    """By points: rank, name and score. By percent (the default) the score carries its percent."""
    run = a_run(scoreboard_show_time="on", revision_mode="separate")
    played(run, "Ema")
    html = text(logged_in.get(url(run, "?view=projector&lang=en")))
    assert "projector" in html and "Ema" in html
    assert "Submitted" not in html and "%" not in html
    results.set_display(run, {"revision_mode": "percent"}, admin_id=ADMIN_ID)
    cache.clear()
    html = text(logged_in.get(url(run, "?view=projector&lang=en")))
    assert "Submitted" not in html and "100 %" in html


def test_projector_view_is_a_clean_page(logged_in):
    """Only the board: no menu, language switch, links, buttons or footer."""
    run = a_run()
    played(run, "Ema")
    body = text(logged_in.get(url(run, "?view=projector&lang=en"))).split("<body", 1)[1]
    assert "Ema" in body
    for leftover in (
        'class="site-bar"',
        "<footer",
        "<button",
        "Normal view",
        "Full screen",
        "<nav",
    ):
        assert leftover not in body, leftover
    assert "<a " not in body


def test_projector_links_open_a_new_window():
    templates = Path(__file__).resolve().parents[2] / "app/api/jinja2"
    names = (
        "admin/_quiz_header.html",
        "admin/run.html",
        "admin/runs.html",
        "public/scoreboard.html",
    )
    for name in names:
        for link in re.findall(r"<a [^>]*view=projector[^>]*>", (templates / name).read_text()):
            assert 'target="_blank"' in link and 'rel="noopener"' in link, (name, link)


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


def test_projector_view_never_marks_an_own_row(admin_user):
    """AC-83: a screen in a room is shared, so it is neutral even in a browser that played."""
    run = a_run(**{SCOREBOARD_LIVE_NAMES: "shown"})
    played(run, "Ema", key="my-browser-key")
    browser = FormClient()
    browser.force_login(admin_user)
    browser.cookies[participants.cookie_name(run)] = "my-browser-key"
    for rest in ("?lang=en&view=projector", "/rows?lang=en&view=projector"):
        html = text(browser.get(url(run, rest)))
        assert "Ema" in html
        assert "data-mine" not in html
        assert "(you)" not in html
    assert text(browser.get(url(run, "?lang=en"))).count("data-mine") == 1  # the own page stays


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
    assert "/scoreboard" not in text(client.get(f"/q/{hidden.quiz.slug}"))


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
    assert '<table class="stack compact">' in text(client.get(url(run)))


@pytest.mark.parametrize("rest", ["?lang=en", "/rows?lang=en"])
@pytest.mark.parametrize("with_cookie", [False, True])
def test_scoreboard_page_and_rows_vary_on_language_and_cookie(rest, with_cookie):
    """AC-142, TD-041: language and the own mark change the answer, so a cache keys on both."""
    run = a_run()
    played(run, "Ema", key="my-browser-key")
    browser = FormClient()
    if with_cookie:
        browser.cookies[participants.cookie_name(run)] = "my-browser-key"
    response = browser.get(url(run, rest))
    assert response.status_code == 200
    varied = {part.strip().lower() for part in response["Vary"].split(",")}
    assert {"accept-language", "cookie"} <= varied
    assert ("no-store" in response["Cache-Control"]) is with_cookie


def test_projector_is_only_for_a_signed_in_admin(client):
    """AC-83: without a login the projector address shows the normal public board.

    The projector shows the score column even where the admin hid it, so a participant who adds
    `?view=projector` must not get it.
    """
    run = a_run(**{SCOREBOARD_SHOW_SCORE: "off"})
    played(run, "Ema", score=7)
    for rest in ("?lang=en&view=projector", "/rows?lang=en&view=projector"):
        html = text(client.get(url(run, rest)))
        assert "Ema" in html
        assert "projector" not in html
        assert '<th scope="col">Score</th>' not in html and "Skóre</th>" not in html


def test_public_page_has_no_projector_link(client):
    run = a_run()
    played(run, "Ema")
    assert "view=projector" not in text(client.get(url(run, "?lang=en")))


def test_admin_sees_the_projector_link_and_the_projector_is_not_cached(logged_in):
    run = a_run()
    played(run, "Ema")
    own = logged_in.get(url(run, "?lang=en"))
    assert "view=projector" in text(own)
    assert own["Cache-Control"] == "private, no-store"
    for rest in ("?lang=en&view=projector", "/rows?lang=en&view=projector"):
        response = logged_in.get(url(run, rest))
        assert "projector" in text(response)
        assert response["Cache-Control"] == "private, no-store"


def test_rows_are_a_compact_table_so_a_phone_shows_one_line_per_place(client):
    run = a_run()
    played(run, "Eva")
    html = text(client.get(url(run, "/rows")))
    assert '<table class="stack compact">' in html
    assert 'class="rank"' in html
    assert 'class="who"' in html


def test_shared_board_lists_the_rows_of_every_run_and_names_the_runs(client):
    """AC-177: the main run's page shows all linked runs' rows and says which runs they are."""
    quiz = published_quiz("kviz", ("cs", "en", "uk"))
    first = a_run(quiz)
    authoring.close_run(first, admin_id=ADMIN_ID)
    second = a_run(quiz)
    played(first, "Anna")
    played(second, "Boris")
    results.share_board(second, [first], admin_id=ADMIN_ID)
    html = text(client.get(url(second)))
    assert "Anna" in html and "Boris" in html
    assert "Společný žebříček běhů 1, 2" in html
    assert "Společný žebříček běhů 1, 2" in text(client.get(url(second, "?lang=cs")))
    assert "Спільна таблиця результатів запусків 1, 2" in text(client.get(url(second, "?lang=uk")))
    own = text(client.get(url(first)))
    assert "Boris" not in own
    assert "Společný žebříček" not in own


def test_a_run_without_a_shared_board_has_no_note(client):
    run = a_run()
    assert "Společný žebříček" not in text(client.get(url(run)))


def _two_revision_runs():
    """Run 1 of 1 point with Anna 1/1 (closed), run 2 of 2 points with Boris 1/2 (open)."""
    quiz = published_quiz("kviz", ("cs", "en", "uk"))
    first = a_run(quiz)
    played(first, "Anna", score=1)
    authoring.close_run(first, admin_id=ADMIN_ID)
    add_question(quiz)
    authoring.publish(quiz, admin_id=ADMIN_ID, decision=authoring.Decision.LET_FINISH)
    second = a_run(quiz)
    played(second, "Boris", score=1)
    return first, second


def test_projector_by_percent_shows_points_of_each_own_maximum_and_the_percent(logged_in):
    """Ranked by percent, a bare score would mislead: each row shows score / max and percent."""
    first, second = _two_revision_runs()
    results.share_board(second, [first], admin_id=ADMIN_ID)
    html = text(logged_in.get(url(second, "?view=projector&lang=en")))
    assert html.index("Anna") < html.index("Boris")
    assert re.search(r"1\s*/\s*1\b.*100 %", html, re.S)
    assert re.search(r"1\s*/\s*2\b.*50 %", html, re.S)


@pytest.mark.parametrize("main_is_second", [True, False])
def test_own_place_on_a_shared_board_says_it_is_within_the_own_run(main_is_second):
    first, second = _two_revision_runs()
    if main_is_second:
        results.share_board(second, [first], admin_id=ADMIN_ID)
    else:
        results.share_board(first, [second], admin_id=ADMIN_ID)
    browser = FormClient()
    html = text(submit_correct(browser, second, start(browser, second)))
    assert "1. z 2 v běhu 2" in html


def test_own_place_without_a_shared_board_names_no_run():
    run = a_run()
    played(run, "Ema", score=1)
    browser = FormClient()
    assert "v běhu" not in text(submit_correct(browser, run, start(browser, run)))
