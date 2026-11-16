"""Shared contract suite: every retention module must pass it."""

from datetime import UTC, datetime

import pytest

from app.contracts import RetentionProvider, RetentionRecord

CUTOFF = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FINGERPRINT = "f" * 64


class RetentionSuite:
    def __init__(self, provider: object) -> None:
        assert isinstance(provider, RetentionProvider)
        self.provider: RetentionProvider = provider

    def run(self) -> None:
        self.satisfies_the_port()
        self.record_then_history_has_exact_counts()
        self.history_is_newest_first_and_limited()
        self.history_pages_by_offset()
        self.for_run_filters()
        self.erased_finds_only_that_fingerprint()
        self.a_record_says_whether_it_has_a_fingerprint_but_not_which()
        self.record_refuses_a_trigger_it_does_not_know()

    def _record(self, run_id: str, fingerprint: str | None = None) -> str:
        return self.provider.record(
            run_id,
            trigger="erasure" if fingerprint else "manual",
            admin_id="admin-1",
            policy="90d",
            cutoff_at=CUTOFF,
            counts={"participants": 2, "attempts": 3},
            fingerprint=fingerprint,
        )

    def _in_history(self, record_id: str) -> RetentionRecord:
        return next(row for row in self.provider.history() if row.id == record_id)

    def satisfies_the_port(self) -> None:
        assert self.provider.id == "local"

    def record_then_history_has_exact_counts(self) -> None:
        record_id = self.provider.record(
            "run-exact",
            trigger="automatic",
            admin_id=None,
            policy="30d",
            cutoff_at=None,
            counts={"participants": 7, "photos": 0},
        )
        row = self._in_history(record_id)
        assert isinstance(row, RetentionRecord)
        assert row.run_id == "run-exact"
        assert row.trigger == "automatic"
        assert row.admin_id is None
        assert row.policy == "30d"
        assert row.cutoff_at is None
        assert row.executed_at is not None
        assert row.counts == {"participants": 7, "photos": 0}
        assert row.has_fingerprint is False

        with_cutoff = self._in_history(self._record("run-cutoff"))
        assert with_cutoff.admin_id == "admin-1"
        assert with_cutoff.cutoff_at == CUTOFF

    def history_is_newest_first_and_limited(self) -> None:
        older = self._record("run-order")
        newer = self._record("run-order")
        ids = [row.id for row in self.provider.history()]
        assert ids.index(newer) < ids.index(older)
        assert len(self.provider.history(limit=1)) == 1
        assert self.provider.history(limit=1)[0].id == ids[0]

    def history_pages_by_offset(self) -> None:
        self._record("run-page")
        self._record("run-page")
        ids = [row.id for row in self.provider.history()]
        assert [row.id for row in self.provider.history(limit=1, offset=1)] == [ids[1]]
        assert self.provider.history(offset=len(ids)) == []

    def for_run_filters(self) -> None:
        mine = self._record("run-mine")
        self._record("run-other")
        assert sorted(row.id for row in self.provider.for_run("run-mine")) == [mine]
        assert self.provider.for_run("run-nobody") == []

    def erased_finds_only_that_fingerprint(self) -> None:
        match = self._record("run-erased", FINGERPRINT)
        self._record("run-erased", "0" * 64)
        self._record("run-erased")
        assert sorted(row.id for row in self.provider.erased(FINGERPRINT)) == [match]
        assert self.provider.erased("1" * 64) == []

    def a_record_says_whether_it_has_a_fingerprint_but_not_which(self) -> None:
        secret = "a" * 64
        row = self._in_history(self._record("run-secret", secret))
        assert row.has_fingerprint is True
        assert not hasattr(row, "fingerprint")
        assert secret not in repr(row)

    def record_refuses_a_trigger_it_does_not_know(self) -> None:
        """The three triggers the port names are taken, any other is a bug of the caller."""
        for trigger in ("automatic", "manual", "erasure"):
            self.provider.record(
                "run-trigger",
                trigger=trigger,
                admin_id=None,
                policy="30d",
                cutoff_at=None,
                counts={},
            )
        before = len(self.provider.for_run("run-trigger"))
        for trigger in ("", "AUTOMATIC", "scheduled", "erasure "):
            with pytest.raises(ValueError):
                self.provider.record(
                    "run-trigger",
                    trigger=trigger,
                    admin_id=None,
                    policy="30d",
                    cutoff_at=None,
                    counts={},
                )
        assert len(self.provider.for_run("run-trigger")) == before == 3
