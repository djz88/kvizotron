"""A quiz change offered to the planned or open run, and the admin's answer (TD-101).

`settle` runs last inside the transaction that saved the quiz: raising rolls the save back, so
nothing is saved half.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain import run_flow, setting_rules
from app.domain.models import Quiz, QuizRun
from app.kernel import audit

FIELD = "flow_choice"
RUN = "run"
NEXT = "next"


@dataclass(frozen=True)
class Change:
    key: str
    kept: str
    new: str


@dataclass(frozen=True)
class Offer:
    run: QuizRun
    changes: list[Change]
    refused: list[setting_rules.Clash]  # empty: the run can take the change


class ChoiceNeeded(Exception):
    def __init__(self, offer: Offer) -> None:
        super().__init__("flow choice needed")
        self.offer = offer


class FlowRefused(Exception):
    def __init__(self, offer: Offer) -> None:
        super().__init__("flow refused")
        self.offer = offer


def _live_run(quiz: Quiz) -> QuizRun | None:
    # `quiz.runs` hides test runs and `one_open_run_per_quiz` allows one live normal run.
    live = (QuizRun.Status.SCHEDULED, QuizRun.Status.OPEN)
    return quiz.runs.filter(status__in=live).first()


def offer_for(quiz: Quiz, before: Mapping[str, str], after: Mapping[str, str]) -> Offer | None:
    run = _live_run(quiz)
    if run is None:
        return None
    kept = run_flow.of(run)
    changes = [
        Change(key, kept[key], after[key])
        for key in run_flow.KEYS
        if before[key] != after[key] and kept[key] != after[key]
    ]
    if not changes:
        return None
    refused = setting_rules.run_clashes(run, kept | {c.key: c.new for c in changes})
    return Offer(run, changes, refused)


def settle(quiz: Quiz, before: Mapping[str, str], choice: str | None, *, admin_id: str) -> None:
    offer = offer_for(quiz, before, run_flow.snapshot(quiz))
    if offer is None:
        return
    if choice not in (RUN, NEXT):
        raise ChoiceNeeded(offer)
    if choice == NEXT:
        return
    if offer.refused:
        raise FlowRefused(offer)
    run = QuizRun.objects.select_for_update().get(pk=offer.run.pk)
    run.flow_json = run_flow.of(run) | {c.key: c.new for c in offer.changes}
    run.save(update_fields=["flow_json"])
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="run.flow_applied",
        entity_type="run",
        entity_id=str(run.id),
        details={"keys": [c.key for c in offer.changes]},
    )
