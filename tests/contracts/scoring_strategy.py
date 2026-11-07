"""Shared contract suite: every scoring strategy must pass it (contracts.md, invariant 2)."""

from decimal import Decimal

from app.contracts import ItemGrade, ScoreBreakdown, ScoringStrategyPlugin


class ScoringStrategyContract:
    plugin: ScoringStrategyPlugin
    settings: dict = {}
    complete = ItemGrade(right=2, wrong=0, total=2)
    empty = ItemGrade(right=0, wrong=0, total=2)

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, ScoringStrategyPlugin)

    def test_label_is_readable_text(self):
        label = str(self.plugin.label())
        assert label.strip() and label != self.plugin.id

    def test_returns_breakdown_within_max_points(self):
        result = self.plugin.evaluate(self.complete, self.settings)
        assert isinstance(result, ScoreBreakdown)
        assert 0 <= result.earned_points <= result.max_points
        assert result.max_points == self.plugin.max_score(self.settings)

    def test_scores_are_decimal(self):
        result = self.plugin.evaluate(self.complete, self.settings)
        assert isinstance(result.earned_points, Decimal)
        assert isinstance(result.max_points, Decimal)
        assert isinstance(self.plugin.max_score(self.settings), Decimal)

    def test_complete_grade_pays_the_maximum(self):
        result = self.plugin.evaluate(self.complete, self.settings)
        assert result.earned_points == result.max_points
        assert result.correct_count == 1

    def test_empty_grade_earns_nothing(self):
        result = self.plugin.evaluate(self.empty, self.settings)
        assert result.earned_points == 0
        assert result.correct_count == 0

    def test_is_repeatable(self):
        first = self.plugin.evaluate(self.complete, self.settings)
        assert self.plugin.evaluate(self.complete, self.settings) == first
