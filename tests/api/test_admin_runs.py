import io
import re
from uuid import uuid7

import pytest
import segno

from app.domain import attempts
from app.domain.models import QuizRun
from tests.domain.helpers import make_quiz, open_quiz_run, published_quiz
from tests.support.client import FormClient

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
    assert "Tento kvíz už má probíhající běh." in text(response)
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
    assert logged_in.get(f"/admin/runs/{run.id}/close").status_code == 200  # only asks
    assert FormClient().post(f"/r/{run.id}/start").status_code != 409
    assert logged_in.post(f"/admin/runs/{run.id}/close")["Location"] == f"/admin/runs/{run.id}"
    assert FormClient().post(f"/r/{run.id}/start").status_code == 409
    assert "Skončil" in text(logged_in.get(f"/admin/runs/{run.id}"))


def test_run_page_has_no_direct_close_form(logged_in):
    run = open_quiz_run()
    html = text(logged_in.get(f"/admin/runs/{run.id}"))
    assert f'action="/admin/runs/{run.id}/close"' not in html
    assert f'href="/admin/runs/{run.id}/close"' in html


def test_close_without_csrf_token_is_403(admin_user):
    run = open_quiz_run()
    client = FormClient(enforce_csrf_checks=True)
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


# AC-177: a shared scoreboard of several runs, set on the Runs page --------------------------


def three_runs(slug="kviz"):
    """Runs 1 and 2 ended, run 3 running."""
    from app.domain import authoring
    from tests.domain.helpers import ADMIN_ID

    quiz = published_quiz(slug)
    for _ in range(2):
        authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    first, second, third = QuizRun.objects.filter(quiz=quiz).order_by("run_no")
    return quiz, first, second, third


def share(client, quiz, main, members):
    data = {"main": str(main.id), "runs": [str(run.id) for run in members]}
    return client.post(f"/admin/quizzes/{quiz.id}/board/share", data)


def test_runs_page_offers_the_shared_board_form(logged_in):
    """AC-177: a checkbox per run, the main run choice and the save button."""
    quiz, first, second, third = three_runs()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    assert '<th class="board-pick">Sdílet</th>' in html
    assert "kulatým tlačítkem vyberte hlavní běh" in html
    assert "Uložit společný žebříček" in html
    for run in (first, second, third):
        assert f'name="runs" value="{run.id}"' in html
        assert f'name="main" value="{run.id}"' in html


def test_the_board_choice_is_one_narrow_column(logged_in):
    """AC-177: the checkbox and the main run choice share one cell, so the table fits (AC-118)."""
    quiz, *_, newest = three_runs()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    cell = re.search(r'<td class="board-pick" data-label="Sdílet">(.*?)</td>', html, re.S).group(1)
    assert f'name="runs" value="{newest.id}"' in cell and f'name="main" value="{newest.id}"' in cell
    assert "Běh 3 do společného žebříčku" in cell and "Běh 3 jako hlavní běh" in cell
    assert "overflow-auto" not in html


def test_sharing_links_the_runs_and_goes_back_to_the_runs_page(logged_in):
    """AC-177: the ticked runs show on the main run's board; the main run is implicit."""
    quiz, first, second, third = three_runs()
    response = share(logged_in, quiz, third, [first, second])
    assert response.status_code == 302
    assert response["Location"] == f"/admin/quizzes/{quiz.id}/runs"
    assert set(QuizRun.objects.filter(board_main=third)) == {first, second}
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    assert "Zrušit společný žebříček" in html
    assert "Společný žebříček běhů 1, 2, 3" in html


def test_the_main_run_alone_in_the_form_is_refused_with_a_message(logged_in):
    quiz, first, second, third = three_runs()
    response = share(logged_in, quiz, third, [third])
    assert response.status_code == 409
    assert "Vyberte aspoň dva běhy." in text(response)
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_no_main_run_chosen_is_a_bad_request(logged_in):
    quiz, first, second, third = three_runs()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/board/share", {"runs": [str(first.id), str(second.id)]}
    )
    assert response.status_code == 400
    assert "Vyberte hlavní běh." in text(response)
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_a_run_of_another_board_is_refused_with_its_number(logged_in):
    quiz, first, second, third = three_runs()
    assert share(logged_in, quiz, second, [first]).status_code == 302
    response = share(logged_in, quiz, third, [first, third])
    assert response.status_code == 409
    assert "Běh 1 už je ve společném žebříčku jiného běhu." in text(response)


def test_a_run_of_another_quiz_is_refused(logged_in):
    quiz, first, second, third = three_runs()
    _other, foreign, *_ = three_runs("jiny")
    response = share(logged_in, quiz, third, [first, foreign])
    assert response.status_code == 409
    assert "Běh patří k jinému kvízu." in text(response)


def test_a_test_run_cannot_be_shared(logged_in):
    from app.domain import authoring, run_links
    from tests.domain.helpers import ADMIN_ID

    quiz, first, second, third = three_runs()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    response = share(logged_in, quiz, third, [link.run])
    assert response.status_code == 409
    assert "Testovací běh nemůže být ve společném žebříčku." in text(response)


def test_the_form_is_not_a_run_that_is_already_a_member_as_main(logged_in):
    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    response = share(logged_in, quiz, first, [second, first])
    assert response.status_code == 409
    assert "Běh 1 je součástí společného žebříčku jiného běhu." in text(response)


def test_splitting_makes_every_board_single_again(logged_in):
    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    response = logged_in.post(f"/admin/runs/{third.id}/board/split")
    assert response.status_code == 302
    assert response["Location"] == f"/admin/quizzes/{quiz.id}/runs"
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_an_archived_quiz_cannot_share_or_split(logged_in):
    from app.domain import authoring
    from tests.domain.helpers import ADMIN_ID

    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    authoring.close_run(third, admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    assert share(logged_in, quiz, third, [first]).status_code == 409
    assert logged_in.post(f"/admin/runs/{third.id}/board/split").status_code == 409
    assert set(QuizRun.objects.filter(board_main=third)) == {first, second}


def test_sharing_needs_a_login(client):
    quiz, first, second, third = three_runs()
    assert share(client, quiz, third, [first]).status_code == 302
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_the_run_page_names_the_combined_runs(logged_in):
    """AC-177: the main run lists them, a member names its main run."""
    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    board = text(logged_in.get(f"/admin/runs/{third.id}/scoreboard"))
    assert "Společný žebříček běhů 1, 2, 3" in board
    member = text(logged_in.get(f"/admin/runs/{first.id}/scoreboard"))
    assert "Je součástí společného žebříčku běhu 3" in member
    assert "Společný žebříček běhů" not in member


def test_deleting_a_planned_member_drops_the_cache_of_its_main_run():
    """AC-177: a planned run that goes leaves no stale row on the main run's cached board."""
    from datetime import timedelta

    from django.core.cache import cache
    from django.utils import timezone

    from app.domain import authoring, results, run_schedule
    from tests.domain.helpers import ADMIN_ID

    quiz = published_quiz("planovany")
    main = authoring.open_run(quiz, admin_id=ADMIN_ID)
    authoring.close_run(main, admin_id=ADMIN_ID)
    member = run_schedule.plan(
        quiz,
        starts_at=timezone.now() + timedelta(days=1),
        deadline_at=None,
        limit_sec=None,
        admin_id=ADMIN_ID,
    )
    results.share_board(main, [member], admin_id=ADMIN_ID)
    results.board(main, audience="public", locale="cs")
    assert cache.get(results._cache_key(main, "cs")) is not None
    run_schedule.cancel_plan(member, admin_id=ADMIN_ID)
    assert cache.get(results._cache_key(main, "cs")) is None


def test_saving_without_archived_runs_shown_keeps_an_archived_member(logged_in):
    """AC-177: a member hidden from the list is not unlinked by saving the list."""
    from app.domain import run_schedule
    from tests.domain.helpers import ADMIN_ID

    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    run_schedule.archive(first, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/runs"))
    assert f'name="runs" value="{first.id}"' not in html
    response = share(logged_in, quiz, third, [second])
    assert response.status_code == 302
    assert set(QuizRun.objects.filter(board_main=third)) == {first, second}


def test_a_main_run_of_another_quiz_is_refused(logged_in):
    quiz, first, second, third = three_runs()
    _other, foreign, _b, _c = three_runs("jiny")
    response = share(logged_in, quiz, foreign, [first, second])
    assert response.status_code == 409
    assert "Běh patří k jinému kvízu." in text(response)
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_a_garbage_main_is_a_missing_main(logged_in):
    quiz, first, second, third = three_runs()
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/board/share", {"main": "garbage", "runs": [str(first.id)]}
    )
    assert response.status_code == 400
    assert "Vyberte hlavní běh." in text(response)


@pytest.mark.parametrize("bad", ["garbage", "00000000-0000-0000-0000-000000000000"])
def test_an_unknown_member_asks_for_a_reload(logged_in, bad):
    quiz, first, second, third = three_runs()
    data = {"main": str(third.id), "runs": [str(first.id), str(second.id), bad]}
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/board/share", data)
    assert response.status_code == 400
    assert "Vybrané běhy se změnily, načtěte stránku znovu." in text(response)
    assert not QuizRun.objects.filter(board_main__isnull=False).exists()


def test_splitting_a_run_that_is_not_a_main_changes_nothing(logged_in):
    quiz, first, second, third = three_runs()
    share(logged_in, quiz, third, [first, second])
    response = logged_in.post(f"/admin/runs/{first.id}/board/split")
    assert response.status_code == 302
    assert set(QuizRun.objects.filter(board_main=third)) == {first, second}


def test_splitting_a_test_run_is_not_found(logged_in):
    from app.domain import authoring, run_links
    from tests.domain.helpers import ADMIN_ID

    quiz, *_ = three_runs()
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    assert logged_in.post(f"/admin/runs/{link.run_id}/board/split").status_code == 404


def test_shared_numbers_lists_a_main_runs_board():
    from app.domain import results
    from tests.domain.helpers import ADMIN_ID

    quiz = published_quiz("cisla")
    from app.domain import authoring

    for _ in range(2):
        authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    last = authoring.open_run(quiz, admin_id=ADMIN_ID)
    first, second, _ = QuizRun.objects.filter(quiz=quiz).order_by("run_no")
    assert results.shared_numbers(last) == []
    results.share_board(last, [first, second], admin_id=ADMIN_ID)
    assert results.shared_numbers(last) == [1, 2, 3]
    assert results.shared_numbers(first) == []
