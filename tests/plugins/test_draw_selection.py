"""Snapshot order, fingerprint and selection of a draw."""

import secrets

from app.plugins.drawings.selection import ManualDrawing

plugin = ManualDrawing()


def test_fingerprint_ignores_input_order():
    assert plugin.fingerprint(["b", "c", "a"]) == plugin.fingerprint(["a", "b", "c", "a"])
    assert plugin.fingerprint(["a", "b"]) != plugin.fingerprint(["a", "b", "c"])


def test_select_returns_distinct_members_in_given_count():
    pool = [f"p{i}" for i in range(20)]
    chosen = plugin.select(pool, 5)
    assert len(chosen) == 5
    assert len(set(chosen)) == 5
    assert set(chosen) <= set(pool)


def test_select_more_than_available_returns_all():
    chosen = plugin.select(["b", "a", "c"], 10)
    assert sorted(chosen) == ["a", "b", "c"]


def test_select_uses_system_random(monkeypatch):
    seen = []

    def fake_sample(self, population, k):
        seen.append((list(population), k))
        return list(population)[:k]

    monkeypatch.setattr(secrets.SystemRandom, "sample", fake_sample)
    assert plugin.select(["c", "a", "b"], 2) == ["a", "b"]
    assert seen == [(["a", "b", "c"], 2)]
