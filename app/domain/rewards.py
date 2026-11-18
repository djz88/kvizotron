"""Reward rules of a run and of a quiz's template, and the settings fixed on the run (C5).

A run gets copies of its rules when it is planned or opened, from the source the settings name.
Their structure (kind, unit, value, minimum, counts) changes only while the run is planned; their
texts change at any time, as they only change what is shown.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import cast

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext_lazy

from app.contracts import (
    ASK_EMAIL,
    REWARD_RUN_KEYS,
    REWARD_SOURCE,
    REWARD_THRESHOLDS,
    WINNER_CONTACT,
    AttemptFigures,
    RewardPlugin,
    ThresholdRule,
)
from app.domain import authoring, data_policy, participants, results, settings
from app.domain.models import Attempt, Participant, Quiz, QuizRun, RewardEntitlement, RewardRule
from app.kernel import audit, registry

__all__ = [
    "CONTACT",
    "PROFILE",
    "REVEAL",
    "RewardConflict",
    "RuleData",
    "RuleInvalid",
    "RuleLocked",
    "ShownReward",
    "conflicts",
    "contact_warning",
    "copy_rules",
    "NO_LONGER_REACHED",
    "NotGrantable",
    "cancel",
    "delete_rule",
    "ensure_allowed",
    "grant_manual",
    "grantable",
    "hand_over",
    "has_rules",
    "messages",
    "of",
    "of_participant",
    "of_run",
    "offered",
    "public_winners",
    "refresh",
    "refresh_run",
    "rules_for_quiz",
    "rules_of",
    "save_rule",
    "save_texts",
    "shown",
    "snapshot",
    "template_of",
    "text",
]

PROFILE = "profile"
REVEAL = "reveal"
CONTACT = "contact"
_MESSAGES = {
    PROFILE: gettext_lazy("Rewards need a data profile that keeps scores."),
    REVEAL: gettext_lazy("Answers after each question cannot go with rewards."),
    CONTACT: gettext_lazy("A draw needs a required e-mail under the chosen contact setting."),
}
TEXT_FIELDS = ("name", "description", "claim")
_TEXT_LIMITS = {"name": 80, "description": 500, "claim": 500}
NAME_LENGTH = _TEXT_LIMITS["name"]
MAX_ALTERNATES = 20
MAX_WINNERS = 1000
DEFAULT_ALTERNATES = 2
_HUNDRED = Decimal(100)
_KINDS = RewardRule.Kind
_UNITS = tuple(RewardRule.Unit)
_MIN_UNITS = (RewardRule.Unit.PERCENT, RewardRule.Unit.POINTS)


class RewardConflict(Exception):
    """Rules that cannot go with the run's other settings; `keys` are the codes above."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(", ".join(keys))
        self.keys = keys

    def messages(self) -> list[str]:
        return messages(self.keys)


class RuleLocked(Exception):
    """The run is no longer planned, so the rule's structure stays as it opened."""


class NotGrantable(Exception):
    """The participant has no submitted attempt, so a manual reward cannot go to them."""


class RuleInvalid(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def messages(keys: list[str]) -> list[str]:
    return [str(_MESSAGES[key]) for key in keys]


# Settings on the run ---------------------------------------------------------------------------


def rules_for_quiz(quiz: Quiz) -> dict[str, str]:
    return {key: settings.resolve(key, quiz=quiz) for key in REWARD_RUN_KEYS}


def snapshot(quiz: Quiz, chosen: Mapping[str, str] | None) -> dict[str, str]:
    """What a run stores: the quiz's values now, with the chosen ones on top."""
    given = {key: chosen[key] for key in REWARD_RUN_KEYS if chosen and chosen.get(key)}
    return rules_for_quiz(quiz) | given


def of(run: QuizRun) -> dict[str, str]:
    """A test run has no plan, so it follows the quiz as it is now."""
    if run.kind == QuizRun.Kind.TEST:
        return rules_for_quiz(run.quiz)
    stored = run.rewards_json or {}
    return {
        key: stored[key] if key in stored else settings.CATALOGUE[key].default
        for key in REWARD_RUN_KEYS
    }


# Rules of a run --------------------------------------------------------------------------------


def _ordered(rows):
    return list(rows.order_by("position", "created_at", "id"))


def rules_of(run: QuizRun) -> list[RewardRule]:
    return _ordered(RewardRule.objects.filter(run=run))


def template_of(quiz: Quiz) -> list[RewardRule]:
    return _ordered(RewardRule.objects.filter(quiz=quiz, run__isnull=True))


def has_rules(run: QuizRun) -> bool:
    """A test run never has any (ADR-0044)."""
    if run.kind == QuizRun.Kind.TEST:
        return False
    return RewardRule.objects.filter(run=run).exists()


def _source_rules(run: QuizRun) -> list[RewardRule]:
    source = settings.resolve(REWARD_SOURCE, quiz=run.quiz)
    if source == "previous_run":
        previous = run.quiz.runs.exclude(pk=run.pk).order_by("-run_no").first()
        if previous is not None:
            return rules_of(previous)
        return template_of(run.quiz)
    if source == "quiz":
        return template_of(run.quiz)
    return []


def copy_rules(run: QuizRun) -> None:
    """Called once, in the transaction that plans or opens the run."""
    if run.kind == QuizRun.Kind.TEST:
        return
    RewardRule.objects.bulk_create(
        [
            RewardRule(
                quiz=run.quiz,
                run=run,
                position=number,
                kind=rule.kind,
                threshold_unit=rule.threshold_unit,
                threshold_value=rule.threshold_value,
                min_unit=rule.min_unit,
                min_value=rule.min_value,
                winners=rule.winners,
                alternates=rule.alternates,
                texts_json=copy.deepcopy(rule.texts_json),
                winners_public=False,
            )
            for number, rule in enumerate(
                (rule for rule in _source_rules(run) if not _plugin_missing(rule)), start=1
            )
        ]
    )


def conflicts(run: QuizRun) -> list[str]:
    """Why the run's rules cannot work; empty for a run without rules."""
    if run.kind == QuizRun.Kind.TEST:
        return []
    kinds = set(RewardRule.objects.filter(run=run).values_list("kind", flat=True))
    if not kinds:
        return []
    found = []
    if data_policy.is_stateless(data_policy.of(run)[data_policy.PROFILE]):
        found.append(PROFILE)
    if settings.resolve(settings.REVEAL_MOMENT, run.quiz) == settings.RevealMoment.AFTER_EACH:
        found.append(REVEAL)
    if (
        of(run)[WINNER_CONTACT] == "require_email"
        and _KINDS.DRAW in kinds
        and participants.rules_of(run)[ASK_EMAIL] != "required"
    ):
        found.append(CONTACT)
    return found


def contact_warning(run: QuizRun) -> bool:
    """Under "warn": the run has a draw but asks for no e-mail, so a winner may be unreachable."""
    return (
        run.kind != QuizRun.Kind.TEST
        and of(run)[WINNER_CONTACT] == "warn"
        and participants.rules_of(run)[ASK_EMAIL] == "off"
        and RewardRule.objects.filter(run=run, kind=_KINDS.DRAW).exists()
    )


def ensure_allowed(run: QuizRun) -> None:
    """Raises `RewardConflict`. Call it inside the transaction that wrote the rules."""
    found = conflicts(run)
    if found:
        raise RewardConflict(found)


# Editing ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleData:
    kind: str
    threshold_unit: str | None = None
    threshold_value: Decimal | None = None
    min_unit: str | None = None
    min_value: Decimal | None = None
    winners: int | None = None
    alternates: int | None = None
    texts: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_STRUCTURE = (
    "kind",
    "threshold_unit",
    "threshold_value",
    "min_unit",
    "min_value",
    "winners",
    "alternates",
)


def _decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise RuleInvalid("value_invalid") from exc
    if not number.is_finite():
        raise RuleInvalid("value_invalid")
    return number


def _amount(unit: str | None, value: object, units: tuple[str, ...]) -> tuple[str, Decimal]:
    if unit not in units or value is None:
        raise RuleInvalid("unit_invalid")
    number = _decimal(value)
    if number <= 0:
        raise RuleInvalid("value_not_positive")
    if unit == RewardRule.Unit.PERCENT and number > _HUNDRED:
        raise RuleInvalid("percent_over_100")
    if unit == RewardRule.Unit.CORRECT and number != number.to_integral_value():
        raise RuleInvalid("value_invalid")
    return str(unit), number


def _structure(data: RuleData) -> dict[str, object]:
    """Only the fields the kind uses; the rest empty, so a comparison sees no leftovers."""
    found: dict[str, object] = dict.fromkeys(_STRUCTURE)
    if data.kind not in _KINDS.values:
        raise RuleInvalid("kind_invalid")
    found["kind"] = data.kind
    if data.kind == _KINDS.THRESHOLD:
        found["threshold_unit"], found["threshold_value"] = _amount(
            data.threshold_unit, data.threshold_value, _UNITS
        )
    if data.kind == _KINDS.DRAW:
        if data.min_unit or data.min_value is not None:
            found["min_unit"], found["min_value"] = _amount(
                data.min_unit, data.min_value, _MIN_UNITS
            )
        winners = data.winners
        if winners is None or isinstance(winners, bool) or not 1 <= winners <= MAX_WINNERS:
            raise RuleInvalid("winners_invalid")
        alternates = DEFAULT_ALTERNATES if data.alternates is None else data.alternates
        if isinstance(alternates, bool) or not 0 <= alternates <= MAX_ALTERNATES:
            raise RuleInvalid("alternates_invalid")
        found["winners"], found["alternates"] = int(winners), int(alternates)
    return found


def _stored_structure(rule: RewardRule) -> dict[str, object]:
    found = {name: getattr(rule, name) for name in _STRUCTURE}
    for name in ("threshold_value", "min_value"):
        if found[name] is not None:
            found[name] = Decimal(str(found[name])).normalize()
    return found


def _same(rule: RewardRule, wanted: Mapping[str, object]) -> bool:
    normal = {
        name: Decimal(str(value)).normalize() if isinstance(value, Decimal) else value
        for name, value in wanted.items()
    }
    return _stored_structure(rule) == normal


def _texts(texts: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    locales = {code for code, _name in django_settings.LANGUAGES}
    found: dict[str, dict[str, str]] = {}
    for locale, values in texts.items():
        if locale not in locales or not isinstance(values, Mapping):
            raise RuleInvalid("locale_invalid")
        row = {}
        for name in TEXT_FIELDS:
            value = values.get(name) or ""
            if not isinstance(value, str):
                raise RuleInvalid("text_invalid")
            value = value.strip()
            if len(value) > _TEXT_LIMITS[name]:
                raise RuleInvalid("text_too_long")
            row[name] = value
        if any(row.values()):
            found[locale] = row
    return found


def _audit(action: str, rule: RewardRule, admin_id: str) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="reward_rule",
        entity_id=str(rule.id),
    )


def _run_now(run_id: object) -> QuizRun:
    """The run as it is now, locked for the rest of the transaction. A test run has no rules."""
    current = QuizRun.all_kinds.select_for_update().filter(pk=run_id).first()
    if current is None or current.kind == QuizRun.Kind.TEST:
        raise RuleLocked(str(run_id))
    return current


def _plugin_missing(rule: RuleData | RewardRule) -> bool:
    """Whether a rule would need a plugin that is disabled now."""
    needs_threshold = rule.kind == RewardRule.Kind.THRESHOLD or (
        rule.kind == RewardRule.Kind.DRAW and bool(rule.min_unit)
    )
    if needs_threshold and "threshold" not in registry.keys("reward"):
        return True
    return rule.kind == RewardRule.Kind.DRAW and "manual" not in registry.keys("drawing")


def save_rule(
    owner: Quiz | QuizRun, data: RuleData, *, rule: RewardRule | None, admin_id: str
) -> RewardRule:
    """A new rule, or a changed one. On an open run only the texts may differ."""
    wanted = _structure(data)
    same_needs = (
        rule is not None
        and rule.kind == wanted["kind"]
        and bool(rule.min_unit) == bool(wanted["min_unit"])
    )
    if _plugin_missing(data) and not same_needs:  # the texts of a rule it has can still change
        raise RuleInvalid("plugin_disabled")
    texts = _texts(data.texts)
    if isinstance(owner, Quiz):
        quiz, run = owner, None
        authoring.ensure_editable(quiz)
    else:
        quiz, run = owner.quiz, owner
    if rule is not None and (
        rule.quiz_id != quiz.id or rule.run_id != (run.id if run is not None else None)
    ):
        raise RuleInvalid("not_this_owner")
    with transaction.atomic():
        current = _run_now(run.id) if run is not None else None
        planned = current is None or current.status == QuizRun.Status.SCHEDULED
        if rule is not None:
            rule = RewardRule.objects.get(pk=rule.pk)
        if not planned and (rule is None or not _same(rule, wanted)):
            raise RuleLocked(str(run.id if run is not None else quiz.id))
        if rule is None:
            rows = RewardRule.objects.filter(quiz=quiz, run=run)
            last = rows.aggregate(last=Max("position"))["last"] or 0
            rule = RewardRule(quiz=quiz, run=run, position=last + 1)
        for name, value in wanted.items():
            setattr(rule, name, value)
        rule.texts_json = texts
        rule.save()
        if current is not None and planned:
            ensure_allowed(current)
        _audit("reward.rule_saved", rule, admin_id)
    return rule


def delete_rule(rule: RewardRule, *, admin_id: str) -> None:
    """A template rule, or a rule of a planned run; copies on other runs stay."""
    with transaction.atomic():
        if rule.run_id is None:
            authoring.ensure_editable(rule.quiz)
        elif _run_now(rule.run_id).status != QuizRun.Status.SCHEDULED:
            raise RuleLocked(str(rule.run_id))
        _audit("reward.rule_deleted", rule, admin_id)
        RewardRule.objects.filter(pk=rule.pk).delete()


def save_texts(rule: RewardRule, texts: Mapping[str, Mapping[str, str]], *, admin_id: str) -> None:
    """Names, descriptions and claim instructions change only what is shown, so at any time."""
    cleaned = _texts(texts)
    if rule.run_id is None:
        authoring.ensure_editable(rule.quiz)
    with transaction.atomic():
        RewardRule.objects.filter(pk=rule.pk).update(texts_json=cleaned)
        _audit("reward.texts_saved", rule, admin_id)
    rule.texts_json = cleaned


# Entitlements ----------------------------------------------------------------------------------

NO_LONGER_REACHED = "no_longer_reached"
_REASON_LIMIT = 200
_STATUS = RewardEntitlement.Status
_SOURCE = RewardEntitlement.Source


def _reward() -> RewardPlugin:
    return cast(RewardPlugin, registry.get("reward", "threshold", include_disabled=True))


def _reached(run: QuizRun, rules: list[RewardRule], figures: AttemptFigures) -> set[str]:
    thresholds = [
        ThresholdRule(
            id=str(rule.id),
            unit=str(rule.threshold_unit),
            value=Decimal(str(rule.threshold_value)),
        )
        for rule in rules
        if rule.kind == _KINDS.THRESHOLD
    ]
    if not thresholds:
        return set()
    return set(_reward().qualifies(thresholds, figures, of(run)[REWARD_THRESHOLDS]))


def _automatic_rules(run: QuizRun) -> list[RewardRule]:
    """The rules a recomputation grants by itself; a test run has none."""
    if run.kind == QuizRun.Kind.TEST:
        return []
    return _ordered(
        RewardRule.objects.filter(run=run, kind__in=[_KINDS.THRESHOLD, _KINDS.PARTICIPATION])
    )


def refresh(participant: Participant) -> None:
    """Call it inside the transaction that changed one of the participant's attempts.

    Grants what the official attempt reaches and cancels the automatic grants it no longer
    reaches. A handed-over entitlement, and one the admin or a draw gave, stays as it is. A rule
    the admin cancelled for this participant is not granted again; one this function cancelled is.
    Participation is granted once and never taken back, and follows any submitted, scored
    attempt of the run whatever the revision mode (addendum of 2026-11-17 to ADR-0053); thresholds
    follow the official attempt. A test run gets nothing.
    """
    run = participant.run
    rules = _automatic_rules(run)
    if rules:
        _recompute(participant, run, rules)


def refresh_run(run: QuizRun) -> None:
    """`refresh` for every participant of the run with a finished attempt (TD-047, ADR-0053).

    Call it inside the transaction that changed which attempt counts without a new attempt: a
    changed revision mode of the run, or the run's switch to another revision under `latest`
    (only that mode filters by revision). It reads the run
    as stored now, so the caller saves the change first. Draws already held stay as they are; a
    test run and a run without threshold or participation rules get nothing.
    """
    current = QuizRun.all_kinds.filter(pk=run.pk).first()
    if current is None:
        return
    rules = _automatic_rules(current)
    if not rules:
        return
    finished = Participant.objects.filter(
        run=current,
        attempts__status__in=Attempt.FINISHED,
        attempts__submitted_at__isnull=False,
    )
    for participant in finished.distinct().order_by("created_at", "id"):
        participant.run = current  # one read of the run, not one per participant
        _recompute(participant, current, rules)


def _recompute(participant: Participant, run: QuizRun, rules: list[RewardRule]) -> None:
    """What `refresh` says, with the run's automatic rules already read."""
    found = results.kept(participant)
    official = found.attempt if found is not None else None
    reached = _reached(run, rules, found.figures) if found is not None else set()
    took_part = official
    if took_part is None and any(rule.kind == _KINDS.PARTICIPATION for rule in rules):
        # participation is "took part", not a place: any submitted, scored attempt of the run
        took_part = (
            Attempt.objects.filter(
                participant=participant,
                run=run,
                status=Attempt.Status.SUBMITTED,
                submitted_at__isnull=False,
                score__isnull=False,
            )
            .order_by("-submitted_at", "-id")
            .first()
        )
    held: dict[object, RewardEntitlement] = {}
    refused: set[object] = set()  # an admin cancelled it: never granted back automatically
    for row in RewardEntitlement.objects.filter(participant=participant):
        if row.status != _STATUS.CANCELLED:
            held[row.rule_id] = row
        elif row.changed_by is not None:
            refused.add(row.rule_id)
    now = timezone.now()
    for rule in rules:
        current = held.get(rule.id)
        wanted = (
            took_part is not None
            if rule.kind == _KINDS.PARTICIPATION
            else official is not None and str(rule.id) in reached
        )
        if wanted and current is None and rule.id not in refused:
            RewardEntitlement.objects.create(
                run=run,
                rule=rule,
                participant=participant,
                attempt=took_part if rule.kind == _KINDS.PARTICIPATION else official,
                status=_STATUS.GRANTED,
                source=_SOURCE.AUTO,
            )
        elif (
            not wanted
            and current is not None
            and rule.kind == _KINDS.THRESHOLD
            and current.source == _SOURCE.AUTO
            and current.status == _STATUS.GRANTED
        ):
            RewardEntitlement.objects.filter(pk=current.pk, status=_STATUS.GRANTED).update(
                status=_STATUS.CANCELLED, reason=NO_LONGER_REACHED, changed_at=now, changed_by=None
            )


def of_participant(participant: Participant) -> list[RewardEntitlement]:
    """What the participant holds now, in the order of the run's rules."""
    return list(
        RewardEntitlement.objects.filter(participant=participant)
        .exclude(status=_STATUS.CANCELLED)
        .select_related("rule")
        .order_by("rule__position", "rule__created_at", "rule__id")
    )


@dataclass(frozen=True)
class ShownReward:
    """What a participant sees of one entitlement; `status` is `granted` or `handed_over`."""

    name: str
    description: str
    claim: str
    status: str


def text(rule: RewardRule, quiz: Quiz, locale: str, name: str) -> str:
    """Each field on its own: the language asked for, else the quiz's default, else empty."""
    texts = rule.texts_json or {}
    for code in (locale, quiz.default_locale):
        value = (texts.get(code) or {}).get(name) or ""
        if value:
            return str(value)
    return ""


def shown(participant: Participant | None, locale: str) -> list[ShownReward]:
    """The participant's own rewards for their result pages; never anything about others."""
    if participant is None:
        return []
    quiz = participant.run.quiz
    return [
        ShownReward(
            name=text(row.rule, quiz, locale, "name"),
            description=text(row.rule, quiz, locale, "description"),
            claim=text(row.rule, quiz, locale, "claim"),
            status=str(row.status),
        )
        for row in of_participant(participant)
    ]


def offered(run: QuizRun, locale: str) -> list[tuple[str, str]]:
    """Name and description of each rule for the quiz page; a test run offers nothing."""
    if run.kind == QuizRun.Kind.TEST:
        return []
    found = []
    for rule in rules_of(run):
        name = text(rule, run.quiz, locale, "name")
        description = text(rule, run.quiz, locale, "description")
        if name or description:
            found.append((name, description))
    return found


def public_winners(run: QuizRun, locale: str) -> list[tuple[str, list[str]]]:
    """Winners of the drawn rules the admin published: nickname, else the board's anonymous label.

    A winner whose participant is gone (D3) is left out; never an e-mail or an id.
    """
    from app.domain import draws  # draws imports this module

    if run.kind == QuizRun.Kind.TEST:
        return []
    numbers: dict[str, int] | None = None
    found = []
    for rule in RewardRule.objects.filter(run=run, kind=_KINDS.DRAW, winners_public=True).order_by(
        "position", "created_at", "id"
    ):
        current = draws.standing(rule)
        if current.draw is None:
            continue
        names = []
        for entry in current.winners:
            who = entry.participant
            if who is None:
                continue
            if who.display_name:
                names.append(who.display_name)
                continue
            if numbers is None:
                numbers = results.participant_numbers(run)
            names.append(results.anonymous_label(run.quiz, locale, numbers[str(who.id)]))
        if names:
            found.append((text(rule, run.quiz, locale, "name"), names))
    return found


def of_run(run: QuizRun) -> list[RewardEntitlement]:
    """Every entitlement of the run, cancelled ones too. Admin only: it holds e-mails."""
    return list(
        RewardEntitlement.objects.filter(run=run)
        .select_related("rule", "participant")
        .order_by("rule__position", "rule__created_at", "created_at", "id")
    )


def grantable(run: QuizRun) -> list[Participant]:
    """Who may get a manual reward: every browser of the run with a submitted attempt."""
    return list(
        Participant.objects.filter(
            run=run, attempts__status=Attempt.Status.SUBMITTED, attempts__submitted_at__isnull=False
        )
        .distinct()
        .order_by("created_at", "id")
    )


def _entitlement_audit(action: str, row: RewardEntitlement, admin_id: str) -> None:
    """Ids of the entitlement and its rule only: never a name, an e-mail or the reason."""
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="reward_entitlement",
        entity_id=str(row.id),
        details={"rule_id": str(row.rule_id)},
    )


def grant_manual(rule: RewardRule, participant: Participant, *, admin_id: str) -> RewardEntitlement:
    """A manual reward, granted at once. One the participant already holds is returned as is."""
    authoring.ensure_editable(participant.run.quiz)
    if participant not in grantable(participant.run):
        raise NotGrantable
    if rule.kind != _KINDS.MANUAL:
        raise RuleInvalid("kind")
    if rule.run_id is None or rule.run_id != participant.run_id:
        raise RuleInvalid("not_this_run")
    with transaction.atomic():
        _run_now(rule.run_id)
        current = (
            RewardEntitlement.objects.filter(rule=rule, participant=participant)
            .exclude(status=_STATUS.CANCELLED)
            .first()
        )
        if current is not None:
            return current
        row = RewardEntitlement.objects.create(
            run_id=rule.run_id,
            rule=rule,
            participant=participant,
            attempt=results.official_attempt(participant),
            status=_STATUS.GRANTED,
            source=_SOURCE.MANUAL,
            changed_at=timezone.now(),
            changed_by=admin_id,
        )
        _entitlement_audit("reward.entitlement_granted", row, admin_id)
    return row


def _change(
    entitlement: RewardEntitlement,
    allowed: tuple[str, ...],
    fields: dict[str, object],
    action: str,
    admin_id: str,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        changed = RewardEntitlement.objects.filter(pk=entitlement.pk, status__in=allowed).update(
            **fields, changed_at=now, changed_by=admin_id
        )
        if not changed:
            raise RuleInvalid("status")
        _entitlement_audit(action, entitlement, admin_id)
    entitlement.refresh_from_db()


def hand_over(entitlement: RewardEntitlement, *, admin_id: str) -> None:
    """Only a granted one; after that no recomputation takes it back."""
    authoring.ensure_editable(entitlement.run.quiz)
    _change(
        entitlement,
        (_STATUS.GRANTED,),
        {"status": _STATUS.HANDED_OVER},
        "reward.entitlement_handed_over",
        admin_id,
    )


def cancel(entitlement: RewardEntitlement, reason: str, *, admin_id: str) -> None:
    """The admin may cancel a granted or a handed-over one, always with a reason."""
    authoring.ensure_editable(entitlement.run.quiz)
    cleaned = (reason or "").strip()
    if not cleaned or len(cleaned) > _REASON_LIMIT:
        raise RuleInvalid("reason")
    _change(
        entitlement,
        (_STATUS.GRANTED, _STATUS.HANDED_OVER),
        {"status": _STATUS.CANCELLED, "reason": cleaned},
        "reward.entitlement_cancelled",
        admin_id,
    )


# Entitlements of a draw (called by `draws` inside its transaction) ------------------------------


def _grant_draw(rule: RewardRule, participant_id: object, *, admin_id: str) -> None:
    """A drawn winner's entitlement; one the participant already holds of the rule stays alone."""
    if (
        RewardEntitlement.objects.filter(rule=rule, participant_id=participant_id)
        .exclude(status=_STATUS.CANCELLED)
        .exists()
    ):
        return
    participant = Participant.objects.select_related("run").get(pk=participant_id)
    row = RewardEntitlement.objects.create(
        run_id=rule.run_id,
        rule=rule,
        participant=participant,
        attempt=results.official_attempt(participant),
        status=_STATUS.GRANTED,
        source=_SOURCE.DRAW,
        changed_at=timezone.now(),
        changed_by=admin_id,
    )
    _entitlement_audit("reward.entitlement_granted", row, admin_id)


def _cancel_draw(
    rule: RewardRule, participant_ids: list[object] | None, reason: str, *, admin_id: str
) -> None:
    """Cancels granted draw entitlements of the rule (of these participants, or all); handed-over
    ones stay. `changed_by` is the admin, whose action caused it."""
    rows = RewardEntitlement.objects.filter(rule=rule, source=_SOURCE.DRAW, status=_STATUS.GRANTED)
    if participant_ids is not None:
        rows = rows.filter(participant_id__in=participant_ids)
    now = timezone.now()
    for row in list(rows):
        RewardEntitlement.objects.filter(pk=row.pk, status=_STATUS.GRANTED).update(
            status=_STATUS.CANCELLED, reason=reason, changed_at=now, changed_by=admin_id
        )
        _entitlement_audit("reward.entitlement_cancelled", row, admin_id)
