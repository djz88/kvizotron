"""Shared contract suite for reward modules (port `reward`)."""

from decimal import Decimal

import pytest

from app.contracts import REWARD_RUN_KEYS, AttemptFigures, RewardPlugin, ThresholdRule
from app.kernel import registry
from app.plugins.rewards.manifest import MANIFEST
from app.plugins.rewards.thresholds import ThresholdReward


class RewardContract:
    plugin: RewardPlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, RewardPlugin)

    def test_share_is_a_decimal(self):
        figures = AttemptFigures(Decimal(8), Decimal(10), 4, 5)
        share = self.plugin.share(ThresholdRule("r", "percent", Decimal(80)), figures)
        assert share == Decimal("0.8")

    def test_qualifies_returns_ids_of_the_given_rules(self):
        figures = AttemptFigures(Decimal(10), Decimal(10), 5, 5)
        rules = [
            ThresholdRule("a", "points", Decimal(1)),
            ThresholdRule("b", "correct", Decimal(1)),
        ]
        assert set(self.plugin.qualifies(rules, figures, "all")) == {"a", "b"}

    def test_nothing_qualifies_from_no_rules(self):
        figures = AttemptFigures(Decimal(10), Decimal(10), 5, 5)
        assert self.plugin.qualifies([], figures, "highest") == []


class TestThresholdReward(RewardContract):
    plugin = ThresholdReward()


@pytest.mark.django_db
def test_registered_under_the_port():
    assert isinstance(registry.get("reward", "threshold"), ThresholdReward)


def test_every_setting_is_run_wide_with_a_reason():
    from app.contracts import REWARD_SOURCE

    found = {item["key"]: item for item in MANIFEST["settings"]}
    assert set(found) == {REWARD_SOURCE, *REWARD_RUN_KEYS}
    for item in found.values():
        assert item["scopes"] == ["global", "quiz"]
        assert item["scope_reason"]
        assert item["group"] == "scoreboard"
        assert item["level"] == "advanced"
        assert item["default"] in item["choices"]
        assert set(item["value_labels"]) == set(item["choices"])
