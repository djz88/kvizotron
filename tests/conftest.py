import pytest

from tests.support.client import FormClient


@pytest.fixture
def client():
    return FormClient()


@pytest.fixture
def graded_type():
    """A question type a person finishes grading."""
    from app.kernel import registry
    from tests.support.graded import TYPE_ID, GradedQuestion

    key = ("question_type", TYPE_ID)
    registry._ports[key] = (GradedQuestion(), "question.number")
    yield TYPE_ID
    del registry._ports[key]


@pytest.fixture(autouse=True)
def _empty_cache():
    """The public scoreboard is cached for seconds; a test starts without what another left."""
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def _empty_limiter():
    """The request limits live in process memory; a test starts without what another counted."""
    from app.api import rate_limit

    rate_limit.reset()


@pytest.fixture
def file_db(tmp_path):
    """A migrated SQLite file with the production options (see `tests/support/file_database.py`)."""
    from tests.support.file_database import file_database

    with file_database(tmp_path) as database:
        yield database
