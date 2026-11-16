"""ADR-0067: existing quizzes keep the admin's own address for their QR code."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0026_run_board_main")]
AFTER = [("domain", "0027_quiz_public_origin")]


@pytest.fixture(autouse=True)
def back_to_latest():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def test_existing_quizzes_have_no_address_of_their_own():
    old = migrate(BEFORE)
    old.get_model("domain", "Quiz").objects.create(
        slug="a", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    quiz = migrate(AFTER).get_model("domain", "Quiz").objects.get(slug="a")
    assert quiz.public_origin == ""
