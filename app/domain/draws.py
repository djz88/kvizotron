"""The prize draw of a draw rule: snapshot, selection, alternates and history (FR-37, FR-38).

Every action appends one `Draw` row with its entries and never changes an earlier one (ADR-0013).
The eligible set is rebuilt from the data at the moment of each action. A draw runs only on a
closed or archived normal run that keeps scores and has nothing waiting for grading. A test run,
and a rule of another kind, are refused as `not_a_draw_rule`.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from django.db import transaction
from django.utils.crypto import salted_hmac

from app.contracts import DrawingPlugin, RewardPlugin, ThresholdRule
from app.domain import authoring, data_policy, grading, results, rewards
from app.domain.models import Draw, DrawEntry, Participant, QuizRun, RewardRule
from app.kernel import audit, events, registry

__all__ = [
    "DrawRefused",
    "Eligible",
    "Standing",
    "draw",
    "move_up",
    "preview",
    "pseudonym",
    "redraw",
    "refusal",
    "set_public",
    "standing",
    "substitute",
]

_ACTION = Draw.Action
_ROLE = DrawEntry.Role
_STARTS = (_ACTION.DRAW, _ACTION.REDRAW)
_AMENDS = (_ACTION.MOVE_UP, _ACTION.SUBSTITUTE)
_DRAWABLE = (QuizRun.Status.CLOSED, QuizRun.Status.ARCHIVED)
_REASON_LIMIT = 200


class DrawRefused(Exception):
    """Why the action cannot happen; nothing was stored."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Eligible:
    participant_ids: list[str]  # in the drawing plugin's order
    fingerprint: str


@dataclass(frozen=True)
class Standing:
    draw: Draw | None  # the draw or redraw that starts the current chain
    winners: list[DrawEntry]  # by position
    alternates: list[DrawEntry]  # still unused, by rank
    history: list[Draw]  # every action of the rule, oldest first
    chain: frozenset[object] = frozenset()  # ids of the history rows of the current chain


def _drawing() -> DrawingPlugin:
    return cast(DrawingPlugin, registry.get("drawing", "manual"))


def _reward() -> RewardPlugin:
    return cast(RewardPlugin, registry.get("reward", "threshold", include_disabled=True))


def pseudonym(participant_id: object) -> str:
    """Keeps a draw readable after D3 drops the participant link (FR-39)."""
    return salted_hmac("kvz-draw", str(participant_id), algorithm="sha256").hexdigest()


def _ensure_draw_rule(rule: RewardRule) -> QuizRun:
    if "manual" not in registry.keys("drawing"):
        raise DrawRefused("plugin_disabled")
    if rule.kind != RewardRule.Kind.DRAW or rule.run_id is None:
        raise DrawRefused("not_a_draw_rule")
    run = QuizRun.all_kinds.get(pk=rule.run_id)
    if run.kind == QuizRun.Kind.TEST:
        raise DrawRefused("not_a_draw_rule")
    return run


def _eligible(rule: RewardRule, run: QuizRun) -> Eligible:
    minimum = None
    if rule.min_unit and rule.min_value is not None:
        minimum = ThresholdRule(
            id=str(rule.id), unit=str(rule.min_unit), value=Decimal(str(rule.min_value))
        )
    found = []
    for participant in Participant.objects.filter(run=run).select_related("run"):
        held = results.kept(participant)
        if held is None:
            continue
        if minimum is not None and not _reward().reached(minimum, held.figures):
            continue
        found.append(str(participant.id))
    plugin = _drawing()
    return Eligible(participant_ids=plugin.order(found), fingerprint=plugin.fingerprint(found))


def preview(rule: RewardRule) -> Eligible:
    """What a draw would draw from now; the action itself builds it again."""
    return _eligible(rule, _ensure_draw_rule(rule))


def _run_refusal(run: QuizRun) -> str | None:
    if run.status not in _DRAWABLE:
        return "run_not_closed"
    if data_policy.is_stateless(data_policy.of(run)[data_policy.PROFILE]):
        return "stateless"
    if grading.waiting(run) > 0:
        return "grading_pending"
    return None


def refusal(rule: RewardRule) -> str | None:
    """Why a draw of the rule would be refused now, read only; the action checks again."""
    try:
        run = _ensure_draw_rule(rule)
    except DrawRefused as refused:
        return refused.reason
    return _run_refusal(run)


def _locked_run(rule: RewardRule) -> QuizRun:
    """Checks the run inside the action's transaction."""
    authoring.ensure_editable(_ensure_draw_rule(rule).quiz)
    run = QuizRun.all_kinds.select_for_update().get(pk=rule.run_id)
    reason = _run_refusal(run)
    if reason is not None:
        raise DrawRefused(reason)
    return run


def _reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned or len(cleaned) > _REASON_LIMIT:
        raise DrawRefused("reason_missing")
    return cleaned


def _rules_version(rule: RewardRule) -> str:
    value = None if rule.min_value is None else f"{Decimal(str(rule.min_value)).normalize():f}"
    structure = {
        "kind": rule.kind,
        "min_unit": rule.min_unit or None,
        "min_value": value,
        "winners": rule.winners,
        "alternates": rule.alternates,
    }
    return hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()


# The current chain ------------------------------------------------------------------------------


def _history(rule: RewardRule) -> list[Draw]:
    return list(Draw.objects.filter(rule=rule).order_by("created_at", "id"))


def _entries(history: list[Draw]) -> dict[object, list[DrawEntry]]:
    """Every entry of the history in one query, by draw; the participants come along."""
    found: dict[object, list[DrawEntry]] = {row.id: [] for row in history}
    rows = DrawEntry.objects.filter(draw_id__in=list(found)).select_related("participant")
    for entry in rows.order_by("draw__created_at", "draw_id", "position", "id"):
        found[entry.draw_id].append(entry)
    return found


def _replay(
    root: Draw | None, history: list[Draw], entries: dict[object, list[DrawEntry]]
) -> tuple[list[DrawEntry], list[DrawEntry]]:
    if root is None:
        return [], []
    rows = entries[root.id]
    winners = {entry.position: entry for entry in rows if entry.role == _ROLE.WINNER}
    alternates = sorted(
        (entry for entry in rows if entry.role == _ROLE.ALTERNATE), key=lambda e: e.position
    )
    for child in history:
        if child.parent_id != root.id or child.action not in _AMENDS:
            continue
        for entry in entries[child.id]:
            if entry.role == _ROLE.WINNER:
                winners[entry.position] = entry
                alternates = [row for row in alternates if row.pseudonym != entry.pseudonym]
    return [winners[position] for position in sorted(winners)], alternates


def _root(history: list[Draw]) -> Draw | None:
    starts = [row for row in history if row.action in _STARTS]
    return starts[-1] if starts else None


def _chain(root: Draw | None, history: list[Draw]) -> frozenset[object]:
    if root is None:
        return frozenset()
    return frozenset(row.id for row in history if row.id == root.id or row.parent_id == root.id)


def standing(rule: RewardRule) -> Standing:
    history = _history(rule)
    root = _root(history)
    winners, alternates = _replay(root, history, _entries(history))
    return Standing(
        draw=root,
        winners=winners,
        alternates=alternates,
        history=history,
        chain=_chain(root, history),
    )


def _chain_drawn(root: Draw, history: list[Draw]) -> tuple[set[str], set[str]]:
    """Participant ids the chain has drawn, and the pseudonyms of entries whose link is gone."""
    ids = list(_chain(root, history))
    linked: set[str] = set()
    orphans: set[str] = set()
    for participant_id, name in DrawEntry.objects.filter(draw_id__in=ids).values_list(
        "participant_id", "pseudonym"
    ):
        if participant_id is None:
            orphans.add(name)
        else:
            linked.add(str(participant_id))
    return linked, orphans


# Storing an action ------------------------------------------------------------------------------


def _store(
    rule: RewardRule,
    run: QuizRun,
    action: str,
    snapshot: Eligible,
    *,
    parent: Draw | None,
    reason: str,
    admin_id: str,
    entries: list[tuple[str, int, str]],  # (participant id, position, role)
    selected: list[str],
    requested: int,
) -> Draw:
    names = [pseudonym(participant_id) for participant_id in selected]
    row = Draw.objects.create(
        run=run,
        rule=rule,
        action=action,
        parent=parent,
        admin_id=admin_id,
        eligible_count=len(snapshot.participant_ids),
        eligible_set_hash=snapshot.fingerprint,
        algorithm=_drawing().algorithm,
        rules_version=_rules_version(rule),
        reason=reason,
        audit_json={"selected": names, "count": len(names), "requested": requested},
    )
    DrawEntry.objects.bulk_create(
        [
            DrawEntry(
                draw=row,
                participant_id=participant_id,
                pseudonym=pseudonym(participant_id),
                position=position,
                role=role,
            )
            for participant_id, position, role in entries
        ]
    )
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=f"draw.{action}",
        entity_type="run",
        entity_id=str(run.id),
        details={
            "draw_id": str(row.id),
            "rule_id": str(rule.id),
            "eligible_count": row.eligible_count,
            "fingerprint": row.eligible_set_hash,
            "selected": names,
        },
    )
    events.emit(
        "draw.completed", {"run_id": str(run.id), "rule_id": str(rule.id), "action": action}
    )
    return row


def _fresh(rule: RewardRule) -> RewardRule:
    return RewardRule.objects.get(pk=rule.pk)


def _new_chain(
    rule: RewardRule, action: str, *, parent: Draw | None, reason: str, admin_id: str
) -> Draw:
    run = _locked_run(rule)
    rule = _fresh(rule)
    snapshot = _eligible(rule, run)
    if not snapshot.participant_ids:
        raise DrawRefused("nobody_eligible")
    if parent is not None:
        rewards._cancel_draw(rule, None, reason, admin_id=admin_id)
    winners = rule.winners or 1
    requested = winners + (rule.alternates or 0)
    selected = _drawing().select(snapshot.participant_ids, requested)
    entries = [
        (who, number + 1, _ROLE.WINNER)
        if number < winners
        else (who, number - winners + 1, _ROLE.ALTERNATE)
        for number, who in enumerate(selected)
    ]
    row = _store(
        rule,
        run,
        action,
        snapshot,
        parent=parent,
        reason=reason,
        admin_id=admin_id,
        entries=entries,
        selected=selected,
        requested=requested,
    )
    for who in selected[:winners]:
        rewards._grant_draw(rule, who, admin_id=admin_id)
    return row


def draw(rule: RewardRule, *, admin_id: str) -> Draw:
    """The first draw of the rule; winners first, then alternates ranked 1..M."""
    with transaction.atomic():
        _locked_run(rule)
        if Draw.objects.filter(rule=rule).exists():
            raise DrawRefused("already_drawn")
        return _new_chain(rule, _ACTION.DRAW, parent=None, reason="", admin_id=admin_id)


def redraw(rule: RewardRule, reason: str, *, admin_id: str) -> Draw:
    """The whole draw again; the superseded chain's granted entitlements are cancelled."""
    cleaned = _reason(reason)
    with transaction.atomic():
        _locked_run(rule)
        root = _root(_history(rule))
        if root is None:
            raise DrawRefused("not_drawn")
        return _new_chain(rule, _ACTION.REDRAW, parent=root, reason=cleaned, admin_id=admin_id)


def _replace(
    rule: RewardRule,
    winner: DrawEntry,
    reason: str,
    admin_id: str,
    action: str,
) -> Draw:
    cleaned = _reason(reason)
    with transaction.atomic():
        run = _locked_run(rule)
        rule = _fresh(rule)
        history = _history(rule)
        root = _root(history)
        winners, alternates = _replay(root, history, _entries(history))
        if root is None or winner.id not in {entry.id for entry in winners}:
            raise DrawRefused("not_drawn")
        snapshot = _eligible(rule, run)
        if action == _ACTION.MOVE_UP:
            # The first alternate who still has a participant and is eligible now; the ones
            # passed over keep their place.
            eligible = set(snapshot.participant_ids)
            ready = [
                str(entry.participant_id)
                for entry in alternates
                if entry.participant_id is not None and str(entry.participant_id) in eligible
            ]
            if not ready:
                raise DrawRefused("no_alternate")
            chosen = ready[0]
            requested = 1
        else:
            # By participant id, so a changed secret key does not let a drawn person back in;
            # the pseudonym only covers entries whose participant link was removed.
            drawn, orphans = _chain_drawn(root, history)
            left = [
                who
                for who in snapshot.participant_ids
                if who not in drawn and pseudonym(who) not in orphans
            ]
            if not left:
                raise DrawRefused("nobody_left")
            chosen = _drawing().select(left, 1)[0]
            requested = 1
        out = str(winner.participant_id) if winner.participant_id is not None else None
        entries = [(chosen, winner.position, _ROLE.WINNER)]
        if out is not None:
            entries.insert(0, (out, winner.position, _ROLE.OUT))
        row = _store(
            rule,
            run,
            action,
            snapshot,
            parent=root,
            reason=cleaned,
            admin_id=admin_id,
            entries=entries,
            selected=[chosen],
            requested=requested,
        )
        if out is not None:
            rewards._cancel_draw(rule, [out], cleaned, admin_id=admin_id)
        rewards._grant_draw(rule, chosen, admin_id=admin_id)
        return row


def move_up(rule: RewardRule, winner: DrawEntry, reason: str, *, admin_id: str) -> Draw:
    """The first remaining alternate who is eligible now takes the winner's place."""
    return _replace(rule, winner, reason, admin_id, _ACTION.MOVE_UP)


def substitute(rule: RewardRule, winner: DrawEntry, reason: str, *, admin_id: str) -> Draw:
    """One new winner from the snapshot, minus everyone the current chain has drawn."""
    return _replace(rule, winner, reason, admin_id, _ACTION.SUBSTITUTE)


def set_public(rule: RewardRule, public: bool, *, admin_id: str) -> None:
    """The only change of `winners_public`; the public scoreboard reads it."""
    authoring.ensure_editable(_ensure_draw_rule(rule).quiz)
    with transaction.atomic():
        RewardRule.objects.filter(pk=rule.pk).update(winners_public=bool(public))
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="draw.winners_public",
            entity_type="reward_rule",
            entity_id=str(rule.id),
            details={"public": bool(public)},
        )
    rule.winners_public = bool(public)
