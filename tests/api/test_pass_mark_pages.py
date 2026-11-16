"""Pass mark, shown (test add-ons): result pages, scoreboard, admin run page and preview."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import OFFICIAL_ATTEMPT, PASS_MARK, SCOREBOARD_SHOW_SCORE, SCOREBOARD_VISIBILITY
from app.domain import authoring, run_links, settings, tokens
from app.domain.models import Attempt, Participant
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    OPTION_B,
    published_quiz,
)
from tests.support.client import FormClient
from tests.support.photos import Player

pytestmark = pytest.mark.django_db
T0 = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


def text(response):
    return response.content.decode()


def a_run(mark="70", questions=10, slug="kviz", **chosen):
    values = {PASS_MARK: mark, SCOREBOARD_VISIBILITY: "live"} | chosen
    return authoring.open_run(
        published_quiz(slug, ("cs", "en", "uk"), questions=questions),
        admin_id=ADMIN_ID,
        results=values,
    )


def stored(run, who, score, minute=0, status=Attempt.Status.SUBMITTED, max_score=10):
    return Attempt.objects.create(
        run=run,
        participant=who,
        revision=run.current_revision,
        status=status,
        submitted_at=T0 + timedelta(minutes=minute),
        score=Decimal(score),
        max_score=Decimal(max_score),
    )


def person(run, name=""):
    return Participant.objects.create(
        run=run, anonymous_key_hash=f"h{Participant.objects.count()}", display_name=name
    )


def private(attempt, lang="en"):
    return text(FormClient().get(f"/v/{tokens.issue_result(attempt.id)}?lang={lang}"))


def test_result_page_shows_attempt_line():
    """AC-172: the result page shows the attempt's own line."""
    run = a_run("70", questions=1)
    player = Player(run)
    html = text(player.plain({f"{player.question('choice')}:options[]": [OPTION_A]}))
    assert "Splněno ✓ — 100 % (hranice 70 %)" in html
    wrong = Player(run)
    html = text(wrong.plain({f"{wrong.question('choice')}:options[]": [OPTION_B]}))
    assert "Nesplněno — 0 % (hranice 70 %)" in html


def test_result_without_mark_unchanged():
    run = a_run("0", questions=1)
    player = Player(run)
    html = text(player.plain({f"{player.question('choice')}:options[]": [OPTION_A]}))
    assert "hranice" not in html and "Splněno" not in html and "Nesplněno" not in html


def test_private_link_shows_attempt_and_kept_line():
    """AC-172: the private link adds the kept-score line."""
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    stored(run, who, 4, 0)
    best = stored(run, who, 8, 1)
    html = private(best)
    assert "Passed ✓ — 80 % (pass mark 70 %)" in html
    assert "Kept score: 80 % (best of 2) — Passed ✓" in html
    low = stored(run, who, 3, 2)
    html = private(low)
    assert "Not passed — 30 % (pass mark 70 %)" in html
    assert "Kept score: 80 % (best of 3) — Passed ✓" in html


def test_one_attempt_shows_only_its_own_line():
    run = a_run("70")
    attempt = stored(run, person(run), 8)
    html = private(attempt)
    assert "Passed ✓ — 80 %" in html and "Kept score" not in html


def test_attempt_without_participant_has_no_kept_line():
    run = a_run("70")
    html = private(stored(run, None, 8))
    assert "Passed ✓ — 80 %" in html and "Kept score" not in html


def test_waiting_attempt_says_so():
    run = a_run("70")
    html = private(stored(run, person(run), 8, status=Attempt.Status.PENDING_GRADING))
    assert "Waiting for grading" in html and "Passed ✓" not in html


def test_other_languages_use_the_catalogue():
    run = a_run("70")
    attempt = stored(run, person(run), 8)
    assert "Splněno ✓ — 80 % (hranice 70 %)" in private(attempt, "cs")
    assert "%(" not in private(attempt, "uk")
    assert "Passed" not in private(attempt, "uk")
    assert "Складено ✓ — 80 % (поріг 70 %)" in private(attempt, "uk")


@pytest.mark.parametrize(
    ("rule", "cs", "uk"),
    [
        ("best", "(nejlepší z 2)", "(найкращий із 2)"),
        ("first", "(první z 2)", "(перший із 2)"),
        ("last", "(poslední z 2)", "(останній із 2)"),
        ("average", "(průměr z 2)", "(середнє з 2)"),
    ],
)
def test_kept_line_is_a_whole_sentence_in_each_language(rule, cs, uk):
    run = a_run("70", **{OFFICIAL_ATTEMPT: rule})
    who = person(run)
    stored(run, who, 8)
    attempt = stored(run, who, 9, 1)
    assert cs in private(attempt, "cs")
    assert uk in private(attempt, "uk")


@pytest.mark.parametrize(
    ("chosen", "view"),
    [({SCOREBOARD_SHOW_SCORE: "off"}, ""), ({}, "&view=projector")],
)
def test_the_tick_stays_without_the_score_column_and_on_the_projector(chosen, view):
    run = a_run("70", **chosen)
    stored(run, person(run, "Ema"), 8)
    stored(run, person(run, "Petr"), 5, 1)
    url = f"/q/{run.quiz.slug}/r/{run.id}/scoreboard?lang=en{view}"
    html = text(FormClient().get(url))
    assert html.count("✓") == 1
    assert 'class="visually-hidden">passed<' in html


def test_a_test_run_judges_against_the_quiz_mark():
    quiz = published_quiz("zkouska", ("cs", "en", "uk"), questions=10)
    settings.set_override(PASS_MARK, quiz, "70", admin_id=ADMIN_ID)
    run = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    ).run
    attempt = stored(run, person(run), 8)
    assert "Passed ✓ — 80 % (pass mark 70 %)" in private(attempt)


def test_private_link_without_mark():
    run = a_run("0")
    html = private(stored(run, person(run), 8))
    assert "pass mark" not in html


def test_public_scoreboard_has_only_a_tick():
    """AC-172: the public scoreboard shows only a tick."""
    run = a_run("70")
    stored(run, person(run, "Ema"), 8)
    stored(run, person(run, "Petr"), 5, 1)
    html = text(FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}/scoreboard?lang=en"))
    assert html.count("✓") == 1
    assert 'class="visually-hidden">passed<' in html
    assert "pass mark" not in html and "Not passed" not in html


def test_scoreboard_without_mark_has_no_tick():
    run = a_run("0")
    stored(run, person(run, "Ema"), 8)
    html = text(FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}/scoreboard?lang=en"))
    assert "✓" not in html


def test_attempts_table_and_statistics(logged_in):
    """AC-172: the attempts table and the statistics show the verdicts."""
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    ema, petr = person(run, "Ema"), person(run, "Petr")
    stored(run, ema, 8, 0)
    stored(run, petr, 5, 1)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Passed: 1 of 2" in html
    assert "<th>Pass mark</th>" in html
    assert "Not passed" in html
    cs = text(logged_in.get(f"/admin/runs/{run.id}?lang=cs"))
    assert "Splnilo: 1 z 2" in cs


def test_no_column_or_share_without_mark(logged_in):
    run = a_run("0")
    stored(run, person(run, "Ema"), 8)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert "Passed:" not in html and "<th>Pass mark</th>" not in html


def test_preview_shows_mark(logged_in):
    quiz = published_quiz("prev", ("cs", "en", "uk"))
    settings.set_override(PASS_MARK, quiz, "70", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview?lang=en"))
    token = html.split('name="attempt_token" value="')[1].split('"')[0]
    question = html.split('data-question="')[1].split('"')[0]
    result = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit",
        {"attempt_token": token, "lang": "en", f"{question}:options[]": [OPTION_A]},
    )
    assert "Passed ✓ — 100 % (pass mark 70 %)" in text(result)


def test_kept_line_says_waiting_when_an_attempt_waits():
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    who = person(run)
    stored(run, who, 4, 0)
    best = stored(run, who, 8, 1)
    stored(run, who, 2, 2, status=Attempt.Status.PENDING_GRADING)
    html = private(best)
    assert "Passed ✓ — 80 % (pass mark 70 %)" in html  # its own line is judged
    assert "Kept score: 80 % (best of 2) — Waiting for grading" in html
    assert "(best of 2) — Passed" not in html and "(best of 2) — Not passed" not in html


def test_percent_never_shows_the_mark_while_not_passed():
    """AC-172: 69.96 % against a mark of 70 reads 69.9 % and not passed, never 70.0 %."""
    from app.api import pass_mark

    shown = pass_mark.line(Decimal("6996"), Decimal("10000"), False, Decimal("70"), "en")
    assert "69.9 %" in shown
    assert shown.startswith("Not passed")


def test_admin_board_tick_has_hidden_text(logged_in):
    """AC-172: the tick of the admin board is read as "passed" by a screen reader too."""
    run = a_run("70", **{OFFICIAL_ATTEMPT: "best"})
    stored(run, person(run, "Ema"), 8, 0)
    html = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert '<span class="visually-hidden">passed</span>' in html
