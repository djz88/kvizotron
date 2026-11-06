"""Shared contract suite: every theme must pass it (contracts.md)."""

from django.template.loader import get_template

from app.contracts import ThemePlugin


class ThemeContract:
    plugin: ThemePlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, ThemePlugin)

    def test_layout_template_loads(self):
        assert get_template(self.plugin.layout_template())
