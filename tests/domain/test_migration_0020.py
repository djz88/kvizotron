"""AC-146: the upgrade fills the address key of every participant that already has an address."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)
BEFORE = [("domain", "0019_retention")]
AFTER = [("domain", "0020_participant_email_key")]


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


def old_run(old):
    quiz = old.get_model("domain", "Quiz").objects.create(
        slug="kviz", title={"cs": "K"}, default_locale="cs", supported_locales=["cs"]
    )
    revision = old.get_model("domain", "QuizRevision").objects.create(quiz=quiz, revision_no=1)
    return old.get_model("domain", "QuizRun").objects.create(
        quiz=quiz, current_revision=revision, kind="normal", run_no=1, status="OPEN"
    )


def test_the_migration_fills_the_key_of_existing_rows():
    """AC-146: strip and casefold, None for no address, the address itself untouched."""
    old = migrate(BEFORE)
    run = old_run(old)
    people = old.get_model("domain", "Participant")
    for number, email in enumerate(["  Jana@Example.ORG ", "a@b.cz", "", None, "   "]):
        people.objects.create(run=run, anonymous_key_hash=f"h{number}", email=email)

    model = migrate(AFTER).get_model("domain", "Participant")

    pairs = {row.anonymous_key_hash: (row.email, row.email_key) for row in model.objects.all()}
    assert pairs == {
        "h0": ("  Jana@Example.ORG ", "jana@example.org"),
        "h1": ("a@b.cz", "a@b.cz"),
        "h2": ("", None),
        "h3": (None, None),
        "h4": ("   ", None),
    }


def test_the_migration_fills_more_rows_than_one_batch():
    """AC-146: batches of 500 reach every row."""
    old = migrate(BEFORE)
    run = old_run(old)
    people = old.get_model("domain", "Participant")
    people.objects.bulk_create(
        people(run=run, anonymous_key_hash=f"h{number}", email=f"P{number}@X.cz")
        for number in range(1203)
    )

    model = migrate(AFTER).get_model("domain", "Participant")

    assert model.objects.filter(email_key__isnull=True).count() == 0
    assert model.objects.get(anonymous_key_hash="h1202").email_key == "p1202@x.cz"


def test_going_back_drops_the_column():
    """AC-146: the reverse removes the key and keeps the addresses."""
    old = migrate(BEFORE)
    run = old_run(old)
    old.get_model("domain", "Participant").objects.create(
        run=run, anonymous_key_hash="h", email="A@B.cz"
    )
    migrate(AFTER)

    back = migrate(BEFORE).get_model("domain", "Participant")

    assert not any(field.name == "email_key" for field in back._meta.get_fields())
    assert back.objects.get().email == "A@B.cz"
