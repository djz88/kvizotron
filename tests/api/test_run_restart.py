"""AC-05: a restarted run is a new run with an empty board; the old results stay in the admin."""

import pytest

from app.contracts import SCOREBOARD_VISIBILITY
from app.domain import authoring
from tests.api.test_admin_scoreboard import played, text
from tests.domain.helpers import ADMIN_ID, published_quiz

pytestmark = pytest.mark.django_db


def test_restart_gives_a_new_run_with_an_empty_board_and_keeps_the_old_results(client, logged_in):
    """AC-05: after close and restart: new run id, empty public board, old run viewable."""
    quiz = published_quiz()
    live = {SCOREBOARD_VISIBILITY: "live"}
    old = authoring.open_run(quiz, admin_id=ADMIN_ID, results=live)
    played(old, "Ema")
    authoring.close_run(old, admin_id=ADMIN_ID)
    new = authoring.open_run(quiz, admin_id=ADMIN_ID, results=live)

    assert (old.run_no, new.run_no) == (1, 2)
    assert new.id != old.id
    new_page = client.get(f"/q/{quiz.slug}/r/{new.id}/scoreboard?lang=en")
    assert new_page.status_code == 200
    assert "Ema" not in text(new_page)
    old_page = client.get(f"/q/{quiz.slug}/r/{old.id}/scoreboard?lang=en")
    assert old_page.status_code == 200
    assert "Ema" in text(old_page)
    assert "Ema" in text(logged_in.get(f"/admin/runs/{old.id}/scoreboard?lang=en"))
    assert "Ema" not in text(logged_in.get(f"/admin/runs/{new.id}/scoreboard?lang=en"))
