from decimal import Decimal

import pytest

from app.contracts import ItemGrade
from app.plugins.scoring.strategies import AllOrNothing, Partial
from tests.contracts.scoring_strategy import ScoringStrategyContract


class TestAllOrNothing(ScoringStrategyContract):
    plugin = AllOrNothing()


class TestPartial(ScoringStrategyContract):
    plugin = Partial()


@pytest.mark.parametrize("strategy", [AllOrNothing(), Partial()])
def test_supports_every_type(strategy):
    assert strategy.supports("choice")
    assert strategy.supports("anything")


@pytest.mark.parametrize("strategy", [AllOrNothing(), Partial()])
def test_points_setting_scales_the_maximum(strategy):
    assert strategy.max_score({"points": 3}) == Decimal(3)
    assert strategy.max_score({}) == Decimal(1)


@pytest.mark.parametrize(
    ("right", "wrong", "total", "earned"),
    [(3, 0, 3, "3"), (2, 0, 3, "2"), (2, 1, 3, "1"), (0, 2, 3, "0"), (1, 3, 3, "0")],
)
def test_partial_pays_right_minus_wrong(right, wrong, total, earned):
    grade = ItemGrade(right, wrong, total)
    assert Partial().evaluate(grade, {"points": 3}).earned_points == Decimal(earned)


def test_partial_three_of_three_is_exactly_the_points():
    assert Partial().evaluate(ItemGrade(3, 0, 3), {"points": 1}).earned_points == Decimal(1)


def test_partial_rounds_to_four_places():
    assert Partial().evaluate(ItemGrade(1, 0, 3), {"points": 1}).earned_points == Decimal("0.3333")


def test_partial_counts_as_correct_only_when_complete():
    assert Partial().evaluate(ItemGrade(1, 0, 3), {}).correct_count == 0
    assert Partial().evaluate(ItemGrade(3, 1, 3), {}).correct_count == 0
    assert Partial().evaluate(ItemGrade(3, 0, 3), {}).correct_count == 1


@pytest.mark.parametrize(
    ("right", "wrong", "total", "earned"), [(3, 0, 3, "5"), (2, 0, 3, "0"), (3, 1, 3, "0")]
)
def test_all_or_nothing(right, wrong, total, earned):
    grade = ItemGrade(right, wrong, total)
    assert AllOrNothing().evaluate(grade, {"points": 5}).earned_points == Decimal(earned)


@pytest.mark.parametrize("strategy", [AllOrNothing(), Partial()])
def test_a_grade_with_no_total_earns_nothing(strategy):
    assert strategy.evaluate(ItemGrade(0, 0, 0), {}).earned_points == 0
