"""Which attempt counts, the order of a scoreboard and score summaries (ADR-0026)."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.contracts import (
    SCOREBOARD_SECOND_SORT,
    TIE_BREAK_POLICY,
    RankedRow,
    ScoreEntry,
    ScoreSummary,
)

BANDS = 10
_CENT = Decimal("0.01")
_SCORE = Decimal("0.0001")  # as scores are stored


def _second(entry: ScoreEntry, second: str) -> tuple[int, float]:
    if second == "duration":
        if entry.duration_ms is None:
            return (1, 0.0)
        return (0, float(entry.duration_ms))
    return (0, entry.submitted_at.timestamp())


class LocalResultView:
    id = "local"
    version = "1.0.0"

    def pick_official(self, entries: Sequence[ScoreEntry], rule: str) -> ScoreEntry:
        if not entries:
            raise ValueError("No attempt to choose from.")
        if rule == "first":
            return min(entries, key=lambda e: (e.submitted_at, e.attempt_id))
        if rule == "best":
            return min(entries, key=lambda e: (-e.score, e.submitted_at, e.attempt_id))
        latest = max(entries, key=lambda e: (e.submitted_at, e.attempt_id))
        if rule == "last":
            return latest
        if rule == "average":
            count = len(entries)
            return replace(
                latest,
                score=(sum((e.score for e in entries), Decimal(0)) / count).quantize(
                    _SCORE, ROUND_HALF_UP
                ),
                max_score=(sum((e.max_score for e in entries), Decimal(0)) / count).quantize(
                    _SCORE, ROUND_HALF_UP
                ),
            )
        raise ValueError(f"Unknown official attempt rule: {rule!r}")

    def rank(
        self, entries: Sequence[ScoreEntry], rules: Mapping[str, str], seed: str
    ) -> list[RankedRow]:
        second = rules.get(SCOREBOARD_SECOND_SORT, "submitted")
        policy = rules.get(TIE_BREAK_POLICY, "shared")

        def level(entry: ScoreEntry) -> tuple[Decimal, tuple[int, float]]:
            return (-entry.score, _second(entry, second))

        def tie(entry: ScoreEntry) -> tuple[str, ...]:
            if policy == "random":
                return (hashlib.sha256(f"{seed}:{entry.key}".encode()).hexdigest(),)
            if policy == "earlier":
                return (entry.submitted_at.isoformat(), entry.attempt_id)
            return (entry.submitted_at.isoformat(), entry.key)

        ordered = sorted(entries, key=lambda e: (level(e), tie(e)))
        rows: list[RankedRow] = []
        for position, entry in enumerate(ordered, start=1):
            if policy == "shared" and rows and level(rows[-1].entry) == level(entry):
                rows.append(RankedRow(rows[-1].rank, entry))
            else:
                rows.append(RankedRow(position, entry))
        return rows

    def summarize(self, scores: Sequence[Decimal], max_score: Decimal) -> ScoreSummary:
        bands = [0] * BANDS
        if not scores:
            return ScoreSummary(0, None, None, None, None, tuple(bands))
        for score in scores:
            index = 0 if max_score <= 0 else min(BANDS - 1, int(score / max_score * BANDS))
            bands[max(index, 0)] += 1
        average = (sum(scores, Decimal(0)) / len(scores)).quantize(_CENT, ROUND_HALF_UP)
        middle = Decimal(median(scores)).quantize(_CENT, ROUND_HALF_UP)
        return ScoreSummary(len(scores), average, middle, min(scores), max(scores), tuple(bands))
