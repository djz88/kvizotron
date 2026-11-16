from collections.abc import Mapping

from app.contracts import (
    AFTER_PASS,
    MAX_ATTEMPTS,
    REPEAT_ATTEMPTS,
    UNFINISHED_ATTEMPT,
    OpenAttempt,
    StartDecision,
)

MAX_NAME = 40
MAX_EMAIL = 254


class BasicParticipantPolicy:
    id = "basic"
    version = "1.0.0"

    def clean_name(self, raw: str) -> str:
        name = " ".join(raw.split())
        if len(name) > MAX_NAME:
            raise ValueError(f"A name has at most {MAX_NAME} characters.")
        return name

    def name_key(self, clean: str) -> str:
        return " ".join(clean.split()).casefold()

    def valid_email(self, raw: str) -> bool:
        if not raw or len(raw) > MAX_EMAIL or any(c.isspace() for c in raw):
            return False
        if raw.count("@") != 1:
            return False
        local, domain = raw.split("@")
        return (
            bool(local)
            and "." in domain
            and not domain.startswith(".")
            and not domain.endswith(".")
        )

    def on_start(
        self,
        rules: Mapping[str, str],
        *,
        finished: bool,
        used: int,
        passed: bool,
        open_attempt: OpenAttempt,
    ) -> StartDecision:
        if rules.get(REPEAT_ATTEMPTS, "allow") == "allow":
            return self._allowed(rules, used, passed, open_attempt)
        if finished:
            return "played"
        if open_attempt == "none":
            return "new"
        unfinished = rules.get(UNFINISHED_ATTEMPT, "continue")
        if unfinished == "used":
            return "played"
        if unfinished == "submitted":
            return "replace"
        return "resume" if open_attempt == "running" else "time_up"

    def _allowed(
        self, rules: Mapping[str, str], used: int, passed: bool, open_attempt: OpenAttempt
    ) -> StartDecision:
        """Repeating is allowed: only a pass that ends the test and a limit can say no."""
        if passed and rules.get(AFTER_PASS, "more") == "stop":
            return "played"
        limit = int(rules.get(MAX_ATTEMPTS) or "0")
        if limit == 0:
            return "new"
        if open_attempt == "none":
            return "new" if used < limit else "played"
        unfinished = rules.get(UNFINISHED_ATTEMPT, "continue")
        if unfinished == "continue" and open_attempt == "running":
            return "resume"
        # Every started attempt counts, so does an expired one, whatever happens to unfinished ones.
        return "replace" if used + 1 < limit else "played"
