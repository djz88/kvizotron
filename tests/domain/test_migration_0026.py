"""AC-177: the upgrade leaves every run on its own board (ADR-0065)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0025_revision_mode_percent")]
AFTER = [("domain", "0026_run_board_main")]


@pytest.fixture(autouse=True)
def back_to_latest():
    """The next transactional test needs every migration, not the one this file stops at."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def old_run(old, slug):
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug=slug, title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    return old.get_model("domain", "QuizRun")._base_manager.create(
        quiz=quiz, current_revision=revision, run_no=1, status="OPEN"
    )


def test_existing_runs_share_no_board():
    run = old_run(migrate(BEFORE), "a")

    runs = migrate(AFTER).get_model("domain", "QuizRun")._base_manager

    assert runs.get(pk=run.pk).board_main_id is None


def test_going_back_drops_the_links():
    run = old_run(migrate(BEFORE), "a")
    after = migrate(AFTER).get_model("domain", "QuizRun")._base_manager
    other = after.create(
        quiz_id=after.get(pk=run.pk).quiz_id,
        current_revision_id=after.get(pk=run.pk).current_revision_id,
        run_no=2,
        status="CLOSED",
        board_main_id=run.pk,
    )

    back = migrate(BEFORE).get_model("domain", "QuizRun")._base_manager

    assert back.filter(pk=other.pk).exists()
