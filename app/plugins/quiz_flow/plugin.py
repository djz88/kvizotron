"""All at once, one by one with going back, one by one without (FR-17).

The page enforces this; it is not a security boundary (ADR-0035).
"""

from collections.abc import Sequence

from app.contracts import JSON

ALL_AT_ONCE = "all_at_once"
STEP_BACK = "step_back"
STEP_NO_BACK = "step_no_back"
AFTER_EACH = "after_each"


class BasicFlow:
    id = "flow.basic"
    version = "1.0.0"

    def modes(self) -> Sequence[str]:
        return (ALL_AT_ONCE, STEP_BACK, STEP_NO_BACK)

    def client_options(self, mode: str, moment: str) -> JSON:
        step = mode in (STEP_BACK, STEP_NO_BACK)
        return {"step": step, "back": mode == STEP_BACK, "check": step and moment == AFTER_EACH}
