"""Shared contract suite: every result view module must pass it (AC-82)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.contracts import (
    SCOREBOARD_SECOND_SORT,
    TIE_BREAK_POLICY,
    RankedRow,
    ResultViewPlugin,
    ScoreEntry,
    ScoreSummary,
)

T0 = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)


def entry(
    key: str,
    score: int,
    minute: int = 0,
    *,
    attempt: str | None = None,
    duration: int | None = None,
    max_score: int = 10,
) -> ScoreEntry:
    return ScoreEntry(
        key=key,
        attempt_id=attempt or f"att-{key}-{minute}",
        name=key,
        score=Decimal(score),
        max_score=Decimal(max_score),
        submitted_at=T0 + timedelta(minutes=minute),
        duration_ms=duration,
    )


def rules(policy: str = "shared", second: str = "submitted") -> dict[str, str]:
    return {TIE_BREAK_POLICY: policy, SCOREBOARD_SECOND_SORT: second}


def keys(rows: list[RankedRow]) -> list[str]:
    return [row.entry.key for row in rows]


class ResultViewContract:
    view: ResultViewPlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.view, ResultViewPlugin)

    def test_pick_last(self):
        found = self.view.pick_official([entry("p", 10, 1), entry("p", 5, 2)], "last")
        assert found.score == 5

    def test_pick_last_with_same_time_takes_the_greater_attempt_id(self):
        found = self.view.pick_official(
            [entry("p", 1, 1, attempt="a"), entry("p", 2, 1, attempt="b")], "last"
        )
        assert found.attempt_id == "b"

    def test_pick_average_is_a_new_entry(self):
        found = self.view.pick_official(
            [entry("p", 10, 1, max_score=20), entry("p", 6, 2, attempt="b", max_score=10)],
            "average",
        )
        assert (found.score, found.max_score, found.attempt_id) == (
            Decimal(8),
            Decimal(15),
            "b",
        )
        assert found.submitted_at == T0 + timedelta(minutes=2)

    def test_unknown_rule_is_refused(self):
        with pytest.raises(ValueError):
            self.view.pick_official([entry("p", 1)], "median")

    def test_best_takes_highest_then_earlier(self):
        found = self.view.pick_official(
            [entry("p", 6, 0), entry("p", 8, 5), entry("p", 8, 9)], "best"
        )
        assert (found.score, found.submitted_at) == (Decimal(8), T0 + timedelta(minutes=5))

    def test_best_with_same_time_falls_back_to_attempt_id(self):
        found = self.view.pick_official(
            [entry("p", 8, 1, attempt="b"), entry("p", 8, 1, attempt="a")], "best"
        )
        assert found.attempt_id == "a"

    def test_first_takes_earliest(self):
        found = self.view.pick_official([entry("p", 8, 5), entry("p", 6, 0)], "first")
        assert found.score == Decimal(6)

    def test_score_orders_first(self):
        rows = self.view.rank([entry("a", 3), entry("b", 9), entry("c", 5)], rules(), "s")
        assert keys(rows) == ["b", "c", "a"]
        assert [row.rank for row in rows] == [1, 2, 3]

    def test_second_sort_by_submission(self):
        rows = self.view.rank([entry("a", 5, 9), entry("b", 5, 1)], rules(), "s")
        assert keys(rows) == ["b", "a"]
        assert [row.rank for row in rows] == [1, 2]

    def test_shared_rank_gives_1_1_3(self):
        rows = self.view.rank(
            [entry("c", 5, 3), entry("a", 9, 1), entry("b", 9, 1), entry("d", 9, 0)],
            rules("shared", "duration"),
            "s",
        )
        assert [row.rank for row in rows] == [1, 1, 1, 4]
        assert keys(rows) == ["d", "a", "b", "c"]  # shown by submission time, then key

    def test_earlier_submission_is_unique_and_falls_back_to_attempt_id(self):
        rows = self.view.rank(
            [entry("a", 9, 1, attempt="z"), entry("b", 9, 1, attempt="y")],
            rules("earlier", "duration"),
            "s",
        )
        assert keys(rows) == ["b", "a"]
        assert [row.rank for row in rows] == [1, 2]

    def test_random_is_the_same_on_every_call_and_differs_by_seed(self):
        many = [entry(f"p{i}", 9, 1) for i in range(12)]
        first = keys(self.view.rank(many, rules("random"), "seed-1"))
        assert first == keys(self.view.rank(list(reversed(many)), rules("random"), "seed-1"))
        assert first != keys(self.view.rank(many, rules("random"), "seed-2"))
        assert [row.rank for row in self.view.rank(many, rules("random"), "seed-1")] == list(
            range(1, 13)
        )

    def test_second_sort_by_duration_puts_missing_last(self):
        rows = self.view.rank(
            [
                entry("a", 5, 0, duration=None),
                entry("b", 5, 1, duration=9000),
                entry("c", 5, 2, duration=4000),
            ],
            rules("earlier", "duration"),
            "s",
        )
        assert keys(rows) == ["c", "b", "a"]

    def test_rank_of_nothing(self):
        assert self.view.rank([], rules(), "s") == []

    def test_summary_of_known_scores(self):
        found = self.view.summarize([Decimal(n) for n in (2, 4, 4, 10)], Decimal(10))
        assert found == ScoreSummary(
            count=4,
            average=Decimal("5.00"),
            median=Decimal("4.00"),
            lowest=Decimal(2),
            highest=Decimal(10),
            bands=(0, 0, 1, 0, 2, 0, 0, 0, 0, 1),
        )

    def test_summary_of_nothing(self):
        found = self.view.summarize([], Decimal(10))
        assert found == ScoreSummary(0, None, None, None, None, (0,) * 10)

    def test_summary_with_max_zero(self):
        found = self.view.summarize([Decimal(0), Decimal(0)], Decimal(0))
        assert found.bands == (2,) + (0,) * 9
