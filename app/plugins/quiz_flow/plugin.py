"""All at once, one by one with going back, one by one without, pages (FR-17, ADR-0052).

The page enforces this; it is not a security boundary (ADR-0035).
"""

from collections.abc import Sequence

from app.contracts import JSON

ALL_AT_ONCE = "all_at_once"
STEP_BACK = "step_back"
STEP_NO_BACK = "step_no_back"
PAGES = "pages"
AFTER_EACH = "after_each"


class BasicFlow:
    id = "flow.basic"
    version = "1.0.0"

    def modes(self) -> Sequence[str]:
        return (ALL_AT_ONCE, STEP_BACK, STEP_NO_BACK, PAGES)

    def client_options(self, mode: str, moment: str) -> JSON:
        step = mode in (STEP_BACK, STEP_NO_BACK, PAGES)
        back = mode in (STEP_BACK, PAGES)
        check = mode in (STEP_BACK, STEP_NO_BACK) and moment == AFTER_EACH
        return {"step": step, "back": back, "check": check, "pages": mode == PAGES}
