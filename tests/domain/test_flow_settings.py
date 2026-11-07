import pytest

from app.domain import settings
from tests.domain.helpers import make_quiz

pytestmark = pytest.mark.django_db


@pytest.fixture
def quiz():
    return make_quiz()


def test_defaults_leave_a_quiz_as_it_is(quiz):
    flow = settings.flow(quiz)
    assert (flow.navigation, flow.moment, flow.level) == ("all_at_once", "never", "verdict")
    assert not flow.shuffle_questions
    assert not flow.shuffle_options
    assert not flow.conflict


def test_after_each_with_all_at_once_is_a_conflict():
    assert settings.is_flow_conflict("all_at_once", "after_each")
    assert not settings.is_flow_conflict("step_back", "after_each")
    assert not settings.is_flow_conflict("step_no_back", "after_each")
    assert not settings.is_flow_conflict("all_at_once", "at_end")


def test_conflict_from_a_global_change_falls_back_to_at_end(quiz):
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=None)
    flow = settings.flow(quiz)
    assert flow.moment == "at_end"
    assert flow.conflict


def test_override_beats_global_and_deleting_it_returns(quiz):
    settings.set_global(settings.NAVIGATION_MODE, "step_back", admin_id=None)
    settings.set_override(settings.NAVIGATION_MODE, quiz, "step_no_back", admin_id=None)
    assert settings.flow(quiz).navigation == "step_no_back"
    settings.set_override(settings.NAVIGATION_MODE, quiz, None, admin_id=None)
    assert settings.flow(quiz).navigation == "step_back"


def test_switches_read_as_booleans(quiz):
    settings.set_override(settings.SHUFFLE_QUESTIONS, quiz, "on", admin_id=None)
    settings.set_override(settings.SHUFFLE_OPTIONS, quiz, "on", admin_id=None)
    flow = settings.flow(quiz)
    assert flow.shuffle_questions
    assert flow.shuffle_options
