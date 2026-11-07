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
