"""Threshold rules on exact values and tiers (AC-10, AC-90)."""

from decimal import Decimal

from app.contracts import AttemptFigures, ThresholdRule
from app.plugins.rewards.thresholds import ThresholdReward

plugin = ThresholdReward()


def rule(id_: str, unit: str, value: str) -> ThresholdRule:
    return ThresholdRule(id_, unit, Decimal(value))


def figures(score: str, max_score: str, correct: int = 0, questions: int = 0) -> AttemptFigures:
    return AttemptFigures(Decimal(score), Decimal(max_score), correct, questions)


def test_four_of_five_is_80_percent_and_misses_90():
    """AC-10: the threshold rule reads 4 of 5 as 80 %, which reaches 80 and misses 90."""
    four = figures("4", "5", 4, 5)
    assert plugin.reached(rule("a", "percent", "80"), four)
    assert not plugin.reached(rule("b", "percent", "90"), four)
    assert not plugin.reached(rule("c", "percent", "80.0001"), four)


def test_three_of_five_correct_reaches_3_correct():
    three = figures("3", "5", 3, 5)
    assert plugin.reached(rule("a", "correct", "3"), three)
    assert not plugin.reached(rule("b", "correct", "4"), three)
    assert plugin.share(rule("a", "correct", "3"), three) == Decimal("0.6")


def test_points_reach_on_equal():
    seven = figures("7", "10", 3, 5)
    assert plugin.reached(rule("a", "points", "7"), seven)
    assert not plugin.reached(rule("b", "points", "7.5"), seven)
    assert plugin.share(rule("a", "points", "7"), seven) == Decimal("0.7")


def test_highest_returns_only_largest_share_of_mixed_units():
    rules = [rule("pct", "percent", "80"), rule("pts", "points", "7"), rule("ok", "correct", "3")]
    assert plugin.qualifies(rules, figures("8", "10", 4, 5), "highest") == ["pct"]


def test_highest_breaks_ties_by_order_of_rules():
    rules = [rule("first", "points", "8"), rule("second", "percent", "80")]
    assert plugin.qualifies(rules, figures("8", "10", 4, 5), "highest") == ["first"]


def test_highest_skips_what_is_not_reached():
    rules = [rule("70", "percent", "70"), rule("90", "percent", "90")]
    assert plugin.qualifies(rules, figures("8", "10", 4, 5), "highest") == ["70"]


def test_all_returns_every_reached():
    rules = [
        rule("pct", "percent", "80"),
        rule("miss", "percent", "90"),
        rule("pts", "points", "7"),
        rule("ok", "correct", "3"),
    ]
    assert plugin.qualifies(rules, figures("8", "10", 4, 5), "all") == ["pct", "pts", "ok"]


def test_zero_max_never_reaches():
    empty = figures("0", "0", 0, 0)
    for unit in ("percent", "points", "correct"):
        tiny = rule(unit, unit, "0.01")
        assert plugin.share(tiny, empty) > 1
        assert not plugin.reached(tiny, empty)
    assert plugin.qualifies([rule("p", "percent", "1")], empty, "all") == []
