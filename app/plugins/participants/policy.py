from collections.abc import Mapping

from app.contracts import (
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
        self, rules: Mapping[str, str], *, finished: bool, open_attempt: OpenAttempt
    ) -> StartDecision:
        if rules.get(REPEAT_ATTEMPTS, "allow") == "allow":
            return "new"
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
