"""Which threshold rules an attempt reaches, on exact values (FR-36)."""

from collections.abc import Sequence
from decimal import Decimal

from app.contracts import AttemptFigures, ThresholdRule

UNITS = ("percent", "points", "correct")
MODES = ("highest", "all")
_NEVER = Decimal("Infinity")  # a share above 1: an attempt with nothing to score reaches nothing


def _unit(rule: ThresholdRule) -> str:
    if rule.unit not in UNITS:
        raise ValueError(f"Unknown threshold unit: {rule.unit}")
    return rule.unit


class ThresholdReward:
    id = "threshold"
    version = "1.0.0"

    def share(self, rule: ThresholdRule, figures: AttemptFigures) -> Decimal:
        unit = _unit(rule)
        if unit == "correct":
            if figures.questions <= 0:
                return _NEVER
            return rule.value / Decimal(figures.questions)
        if figures.max_score <= 0:
            return _NEVER
        if unit == "percent":
            return rule.value / Decimal(100)
        return rule.value / figures.max_score

    def reached(self, rule: ThresholdRule, figures: AttemptFigures) -> bool:
        unit = _unit(rule)
        if unit == "correct":
            return figures.questions > 0 and Decimal(figures.correct) >= rule.value
        if figures.max_score <= 0:
            return False
        if unit == "percent":
            return figures.score * 100 >= rule.value * figures.max_score
        return figures.score >= rule.value

    def qualifies(
        self, rules: Sequence[ThresholdRule], figures: AttemptFigures, mode: str
    ) -> list[str]:
        if mode not in MODES:
            raise ValueError(f"Unknown threshold mode: {mode}")
        reached = [rule for rule in rules if self.reached(rule, figures)]
        if mode == "all":
            return [rule.id for rule in reached]
        best: ThresholdRule | None = None
        best_share = Decimal(0)
        for rule in reached:
            share = self.share(rule, figures)
            if best is None or share > best_share:
                best, best_share = rule, share
        return [] if best is None else [best.id]
