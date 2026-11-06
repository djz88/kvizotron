from app.plugins.scoring.strategies import AllOrNothing
from tests.contracts.scoring_strategy import ScoringStrategyContract

DEFINITION = {
    "prompt": {"cs": "Q"},
    "options": [{"id": "a", "text": {"cs": "A"}}, {"id": "b", "text": {"cs": "B"}}],
    "correct": "b",
}


class TestAllOrNothing(ScoringStrategyContract):
    plugin = AllOrNothing()
    definition = DEFINITION
    correct_answer = {"option": "b"}
    wrong_answer = {"option": "a"}


def test_supports_only_choice_single():
    assert AllOrNothing().supports("choice.single")
    assert not AllOrNothing().supports("number")


def test_points_setting_scales_score():
    result = AllOrNothing().evaluate(DEFINITION, {"option": "b"}, {"points": 3})
    assert (result.earned_points, result.max_points, result.correct_count) == (3.0, 3.0, 1)


def test_wrong_answer_counts_as_not_correct():
    assert AllOrNothing().evaluate(DEFINITION, {"option": "a"}, {}).correct_count == 0
