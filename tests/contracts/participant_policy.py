"""Shared contract suite: every participant policy module must pass it."""

import pytest

from app.contracts import (
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
        assert self.policy.on_start(rules, finished=finished, open_attempt=open_attempt) == decision
