"""Snapshot order, fingerprint and secure selection of a draw (FR-37, ADR-0013)."""

import hashlib
import secrets
from collections.abc import Iterable


class ManualDrawing:
    id = "manual"
    version = "1.0.0"
    algorithm = "secrets.SystemRandom.sample+sha256"

    def order(self, ids: Iterable[str]) -> list[str]:
        return sorted(set(ids))

    def fingerprint(self, ids: Iterable[str]) -> str:
        return hashlib.sha256("\n".join(self.order(ids)).encode()).hexdigest()

    def select(self, ids: Iterable[str], count: int) -> list[str]:
        if count < 0:
            raise ValueError("A draw selects zero or more.")
        snapshot = self.order(ids)
        return secrets.SystemRandom().sample(snapshot, min(count, len(snapshot)))
