"""AC-176: the scoreboard button of the quiz page and the boards of earlier runs."""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.contracts import ARCHIVED_RESULTS, SCOREBOARD_RUNS, SCOREBOARD_VISIBILITY
from app.domain import authoring, clock, run_links, run_schedule, settings
from app.domain.models import Attempt, QuizRun
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db


def a_quiz():
    return published_quiz("kviz", ("cs", "en", "uk"))


def opened(quiz, visibility="live", **chosen):
    values = {SCOREBOARD_VISIBILITY: visibility} | chosen
    return authoring.open_run(quiz, admin_id=ADMIN_ID, results=values)


def closed(quiz, visibility="live", **chosen):
    run = opened(quiz, visibility, **chosen)
    authoring.close_run(run, admin_id=ADMIN_ID)
    return run


def board(run):
    return f"/q/{run.quiz.slug}/r/{run.id}/scoreboard"


def page(client, quiz):
    return client.get(f"/q/{quiz.slug}?lang=en").content.decode()


def earlier_links(html):
    return re.findall(r'<li><a href="(/q/[^"]+/scoreboard)\?lang=en">', html)


def test_the_scoreboard_is_a_full_width_button(client):
    quiz = a_quiz()
    run = opened(quiz)
    html = page(client, quiz)
    assert re.search(rf'<a href="{board(run)}\?lang=en" role="button" class="wide outline"', html)


def test_by_default_only_the_current_run_is_offered(client):
    """AC-176: the default shows the current run's board only."""
    quiz = a_quiz()
    first = closed(quiz)
    second = opened(quiz)
    html = page(client, quiz)
    assert board(second) in html
    assert board(first) not in html
    assert client.get(board(first)).status_code == 200  # its own address still works


def test_all_runs_lists_the_earlier_public_boards_newest_first(client):
    """AC-176: "all runs" adds the earlier runs whose board is public, newest first."""
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    first = closed(quiz)
    hidden = closed(quiz, "hidden")
    third = closed(quiz)
    run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID)
    current = opened(quiz)
    html = page(client, quiz)
    assert re.search(rf'<a href="{board(current)}\?lang=en" role="button"', html)
    assert earlier_links(html) == [board(third), board(first)]
    assert board(hidden) not in html
    day = clock.local_date(first.opened_at).isoformat()
    assert f"Run 1 · {day}" in html and f"Run 3 · {day}" in html


def test_the_global_value_is_inherited(client):
    quiz = a_quiz()
    settings.set_global(SCOREBOARD_RUNS, "all", admin_id=None)
    first = closed(quiz)
    opened(quiz)
    assert earlier_links(page(client, quiz)) == [board(first)]


def test_a_quiz_that_is_not_running_lists_the_earlier_boards_too(client):
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    first = closed(quiz)
    last = closed(quiz)
    html = page(client, quiz)
    assert re.search(rf'<a href="{board(last)}\?lang=en" role="button" class="wide outline"', html)
    assert earlier_links(html) == [board(first)]


def test_earlier_boards_show_without_a_board_of_the_current_run(client):
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    first = closed(quiz)
    current = opened(quiz, "hidden")
    html = page(client, quiz)
    assert board(current) not in html
    assert earlier_links(html) == [board(first)]


def test_the_setting_is_on_the_quiz_form(showing_all):
    quiz = a_quiz()
    url = f"/admin/quizzes/{quiz.id}/settings"
    html = showing_all.get(url).content.decode()
    assert f'name="{SCOREBOARD_RUNS}"' in html
    assert showing_all.post(url, {"slug": quiz.slug, SCOREBOARD_RUNS: "all"}).status_code == 302
    assert settings.quiz_override(SCOREBOARD_RUNS, quiz) == "all"


def test_runs_whose_board_is_not_public_now_are_left_out(client):
    """AC-176: archived without public results, deleted data and waiting grading are not listed."""
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    shown = closed(quiz)
    archived = closed(quiz)
    run_schedule.archive(archived, admin_id=ADMIN_ID)
    public_archive = closed(quiz, **{ARCHIVED_RESULTS: "on"})
    run_schedule.archive(public_archive, admin_id=ADMIN_ID)
    deleted = closed(quiz)
    QuizRun.objects.filter(pk=deleted.pk).update(data_deleted_at=datetime.now(UTC))
    waiting = closed(quiz)
    Attempt.objects.create(
        run=waiting,
        revision=waiting.current_revision,
        status=Attempt.Status.PENDING_GRADING,
        submitted_at=datetime.now(UTC),
        score=Decimal(0),
        max_score=Decimal(1),
    )
    opened(quiz)
    assert earlier_links(page(client, quiz)) == [board(public_archive), board(shown)]


def test_clearing_the_quiz_override_falls_back_to_the_global_value(client):
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    closed(quiz)
    opened(quiz)
    assert earlier_links(page(client, quiz))
    settings.set_override(SCOREBOARD_RUNS, quiz, None, admin_id=ADMIN_ID)
    assert earlier_links(page(client, quiz)) == []


def test_the_labels_follow_the_language_of_the_page(client):
    """A language the quiz does not have falls back for the whole page, labels included."""
    quiz = published_quiz("dvojjazycny", ("cs", "en"))
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    closed(quiz)
    opened(quiz)
    html = client.get(f"/q/{quiz.slug}?lang=uk").content.decode()
    assert 'lang="cs"' in html
    assert "Běh 1 · " in html and "Запуск" not in html
    assert "Žebříčky dalších běhů" in html


def test_the_list_costs_the_same_queries_whatever_the_number_of_runs(client):
    quiz = a_quiz()
    settings.set_override(SCOREBOARD_RUNS, quiz, "all", admin_id=ADMIN_ID)
    closed(quiz)
    current = opened(quiz)
    page(client, quiz)  # warm caches of the first load

    def counted():
        with CaptureQueriesContext(connection) as queries:
            html = page(client, quiz)
        return len(queries), len(earlier_links(html))

    few, listed = counted()
    authoring.close_run(current, admin_id=ADMIN_ID)
    for _ in range(5):
        closed(quiz)
    opened(quiz)
    many, more = counted()
    assert (listed, more) == (1, 7)
    assert many == few
