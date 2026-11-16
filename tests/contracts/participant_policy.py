"""Shared contract suite: every participant policy module must pass it."""

import pytest

from app.contracts import (
    AFTER_PASS,
    MAX_ATTEMPTS,
    REPEAT_ATTEMPTS,
    UNFINISHED_ATTEMPT,
    ParticipantPolicyPlugin,
)

# (repeat, unfinished, finished, open attempt, decision)
START_TABLE = [
    *[
        ("allow", unfinished, finished, open_attempt, "new")
        for unfinished in ("continue", "used", "submitted")
        for finished in (True, False)
        for open_attempt in ("none", "running", "expired")
    ],
    *[
        ("forbid", unfinished, True, open_attempt, "played")
        for unfinished in ("continue", "used", "submitted")
        for open_attempt in ("none", "running", "expired")
    ],
    ("forbid", "continue", False, "running", "resume"),
    ("forbid", "continue", False, "expired", "time_up"),
    ("forbid", "used", False, "running", "played"),
    ("forbid", "used", False, "expired", "played"),
    ("forbid", "submitted", False, "running", "replace"),
    ("forbid", "submitted", False, "expired", "replace"),
    *[
        ("forbid", unfinished, False, "none", "new")
        for unfinished in ("continue", "used", "submitted")
    ],
]

# (max attempts, after pass, passed, unfinished, used, open attempt, decision); repeat is allow
LIMIT_TABLE = [
    ("2", "more", False, "continue", 0, "none", "new"),
    ("2", "more", False, "continue", 2, "none", "played"),
    ("2", "more", False, "continue", 1, "running", "resume"),
    ("2", "more", False, "continue", 1, "expired", "played"),
    ("3", "more", False, "continue", 1, "expired", "replace"),
    ("2", "more", False, "submitted", 0, "running", "replace"),
    ("2", "more", False, "submitted", 1, "running", "played"),
    ("2", "more", False, "used", 0, "running", "replace"),
    ("2", "more", False, "used", 1, "expired", "played"),
    ("3", "stop", True, "continue", 1, "none", "played"),
    ("3", "stop", True, "continue", 1, "running", "played"),
    ("3", "stop", False, "continue", 1, "none", "new"),
    ("3", "more", True, "continue", 1, "none", "new"),
    ("0", "stop", True, "continue", 1, "none", "played"),
    ("0", "more", True, "continue", 9, "none", "new"),
]


class ParticipantPolicyContract:
    policy: ParticipantPolicyPlugin

    def test_satisfies_protocol(self):
        assert isinstance(self.policy, ParticipantPolicyPlugin)

    def test_clean_name_collapses_spaces(self):
        assert self.policy.clean_name("  Žába \t Ok ") == "Žába Ok"

    def test_blank_name_is_empty(self):
        assert self.policy.clean_name("   ") == ""

    def test_name_over_40_is_refused(self):
        with pytest.raises(ValueError):
            self.policy.clean_name("x" * 41)
        assert self.policy.clean_name("x" * 40) == "x" * 40

    def test_name_key_ignores_case(self):
        assert self.policy.name_key("Žába Ok") == self.policy.name_key("žába ok")

    def test_email_format(self):
        assert self.policy.valid_email("a@b.cz")
        for bad in ("a@b", "ab.cz", "a b@c.cz", "", "@b.cz", "a@@b.cz"):
            assert not self.policy.valid_email(bad)

    @pytest.mark.parametrize(
        ("repeat", "unfinished", "finished", "open_attempt", "decision"), START_TABLE
    )
    def test_on_start_table(self, repeat, unfinished, finished, open_attempt, decision):
        rules = {REPEAT_ATTEMPTS: repeat, UNFINISHED_ATTEMPT: unfinished}
        assert (
            self.policy.on_start(
                rules, finished=finished, used=0, passed=False, open_attempt=open_attempt
            )
            == decision
        )

    @pytest.mark.parametrize(
        ("limit", "after_pass", "passed", "unfinished", "used", "open_attempt", "decision"),
        LIMIT_TABLE,
    )
    def test_on_start_limit_table(
        self, limit, after_pass, passed, unfinished, used, open_attempt, decision
    ):
        rules = {
            REPEAT_ATTEMPTS: "allow",
            UNFINISHED_ATTEMPT: unfinished,
            MAX_ATTEMPTS: limit,
            AFTER_PASS: after_pass,
        }
        assert (
            self.policy.on_start(
                rules, finished=used > 0, used=used, passed=passed, open_attempt=open_attempt
            )
            == decision
        )

    def test_forbid_submitted_still_restarts(self):
        rules = {REPEAT_ATTEMPTS: "forbid", UNFINISHED_ATTEMPT: "submitted"}
        decision = self.policy.on_start(
            rules, finished=False, used=5, passed=False, open_attempt="running"
        )
        assert decision == "replace"

    def test_forbid_ignores_limit_and_pass(self):
        rules = {REPEAT_ATTEMPTS: "forbid", MAX_ATTEMPTS: "5", AFTER_PASS: "more"}
        decision = self.policy.on_start(
            rules, finished=True, used=1, passed=True, open_attempt="none"
        )
        assert decision == "played"
