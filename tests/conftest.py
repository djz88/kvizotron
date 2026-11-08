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
