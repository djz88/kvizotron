"""Shared contract suite for drawing modules (port `drawing`)."""

import hashlib

import pytest

from app.contracts import DrawingPlugin
from app.kernel import registry
from app.plugins.drawings.manifest import MANIFEST
from app.plugins.drawings.selection import ManualDrawing


class DrawingContract:
    plugin: DrawingPlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.plugin, DrawingPlugin)

    def test_names_its_algorithm(self):
        assert self.plugin.algorithm

    def test_order_is_sorted_and_unique(self):
        assert self.plugin.order(["c", "a", "b", "a"]) == ["a", "b", "c"]

    def test_fingerprint_is_sha256_of_the_order(self):
        expected = hashlib.sha256(b"a\nb\nc").hexdigest()
        assert self.plugin.fingerprint(["c", "b", "a"]) == expected

    def test_select_from_nobody_is_empty(self):
        assert self.plugin.select([], 3) == []


class TestManualDrawing(DrawingContract):
    plugin = ManualDrawing()


@pytest.mark.django_db
def test_registered_under_the_port():
    assert isinstance(registry.get("drawing", "manual"), ManualDrawing)


def test_algorithm_is_the_stated_one():
    assert ManualDrawing().algorithm == "secrets.SystemRandom.sample+sha256"


def test_no_settings():
    assert MANIFEST["settings"] == []
