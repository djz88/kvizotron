"""Shared contract suite: every scoring strategy must pass it (contracts.md, invariant 2)."""

from app.contracts import ScoreBreakdown, ScoringStrategyPlugin


class ScoringStrategyContract:
    plugin: ScoringStrategyPlugin
    definition: dict
    correct_answer: dict
    wrong_answer: dict
    settings: dict = {}

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, ScoringStrategyPlugin)

    def test_returns_breakdown_within_max_points(self):
        result = self.plugin.evaluate(self.definition, self.correct_answer, self.settings)
        assert isinstance(result, ScoreBreakdown)
        assert 0 <= result.earned_points <= result.max_points
        assert result.max_points == self.plugin.max_score(self.definition, self.settings)

    def test_wrong_answer_earns_less(self):
        right = self.plugin.evaluate(self.definition, self.correct_answer, self.settings)
        wrong = self.plugin.evaluate(self.definition, self.wrong_answer, self.settings)
        assert wrong.earned_points < right.earned_points

    def test_client_supplied_score_is_ignored(self):
        forged = self.wrong_answer | {"score": 999, "earned_points": 999, "correct": True}
        honest = self.plugin.evaluate(self.definition, self.wrong_answer, self.settings)
        assert self.plugin.evaluate(self.definition, forged, self.settings) == honest

    def test_is_repeatable(self):
        first = self.plugin.evaluate(self.definition, self.correct_answer, self.settings)
        assert self.plugin.evaluate(self.definition, self.correct_answer, self.settings) == first
