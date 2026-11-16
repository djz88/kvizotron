"""Shared contract suite: every module that provides quiz types must pass it (ADR-0062)."""

import pytest

from app.contracts import QuizTypePlugin
from app.domain import setting_rules, settings


class QuizTypeContract:
    plugins: list

    def test_satisfies_protocol(self):
        for plugin in self.plugins:
            assert isinstance(plugin, QuizTypePlugin), plugin.id

    def test_label_and_description_not_empty(self):
        for plugin in self.plugins:
            assert plugin.label().strip(), plugin.id
            assert plugin.description().strip(), plugin.id

    def test_every_key_is_a_quiz_setting(self):
        for plugin in self.plugins:
            for key in plugin.values():
                assert key in settings.CATALOGUE, (plugin.id, key)
                assert "quiz" in settings.CATALOGUE[key].scopes, (plugin.id, key)

    def test_every_value_is_offered(self):
        for plugin in self.plugins:
            for key, value in plugin.values().items():
                assert value in settings.CATALOGUE[key].choices, (plugin.id, key, value)

    @pytest.mark.django_db
    def test_values_do_not_clash(self):
        """The rules of the settings forms; clashes with planned or open runs depend on runs."""
        defaults = {key: definition.default for key, definition in settings.CATALOGUE.items()}
        of_runs = (setting_rules.RUN_BOARD, setting_rules.RUN_REWARDS)
        for plugin in self.plugins:
            found = setting_rules.clashes(defaults | plugin.values(), None)
            reasons = [c.reason for c in found if c.reason not in of_runs]
            assert reasons == [], plugin.id

    def test_reset_type_has_no_values(self):
        for plugin in self.plugins:
            if plugin.resets_all:
                assert plugin.values() == {}, plugin.id

    def test_orders_are_unique(self):
        orders = [plugin.order for plugin in self.plugins]
        assert len(orders) == len(set(orders))

    def test_values_cannot_be_changed_from_outside(self):
        for plugin in self.plugins:
            values = plugin.values()
            if isinstance(values, dict):
                values["navigation_mode"] = "changed"
            assert plugin.values().get("navigation_mode") != "changed", plugin.id
