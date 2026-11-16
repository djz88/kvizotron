"""Rules about participants, fixed on the run when it is planned or opened (ADR-0049)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, QuerySet
from django.utils.crypto import salted_hmac

from app.contracts import (
    AFTER_PASS,
    ASK_EMAIL,
    ASK_NAME,
    DUPLICATE_NAMES,
    MAX_ATTEMPTS,
    PARTICIPANT_KEYS,
    REPEAT_ATTEMPTS,
    OpenAttempt,
    ParticipantPolicyPlugin,
    StartDecision,
)
from app.domain import authoring, results, settings
from app.domain.models import Attempt, Participant, Quiz, QuizRun
from app.kernel import audit, registry

__all__ = [
    "AttemptRow",
    "COOKIE_MAX_AGE",
    "COOKIE_PREFIX",
    "PARTICIPANT_KEYS",
    "Begin",
    "Identity",
    "Missing",
    "NAME_LENGTH",
    "NameRefused",
    "attempt_rows",
    "attempts_left",
    "begin",
    "claim_name",
    "cookie_name",
    "find",
    "find_or_create",
    "key_hash",
    "missing",
    "name_is_taken",
    "needs_identity",
    "needs_participant",
    "read_identity",
    "rename",
    "rules_for_quiz",
    "rules_of",
    "snapshot",
    "start_decision",
]

NAME_LENGTH = 40  # the length of `Participant.display_name`
COOKIE_PREFIX = "kvz_p_"
COOKIE_MAX_AGE = 30 * 24 * 3600


def rules_for_quiz(quiz: Quiz) -> dict[str, str]:
    return {key: settings.resolve(key, quiz=quiz) for key in PARTICIPANT_KEYS}


def snapshot(quiz: Quiz, rules: Mapping[str, str] | None) -> dict[str, str]:
    """What a run stores: the quiz's rules as they are now, with the given values on top."""
    chosen = {key: rules[key] for key in PARTICIPANT_KEYS if rules and rules.get(key)}
    return rules_for_quiz(quiz) | chosen


def rules_of(run: QuizRun) -> dict[str, str]:
    """A test run has no plan, so it follows the quiz as it is now, and may repeat."""
    if run.kind == QuizRun.Kind.TEST:
        # A test link has no browser to count: it repeats, with no limit and no stop.
        return rules_for_quiz(run.quiz) | {
            REPEAT_ATTEMPTS: "allow",
            MAX_ATTEMPTS: "0",
            AFTER_PASS: "more",
        }
    stored = run.participant_rules_json or {}
    return {
        key: stored[key] if key in stored else settings.CATALOGUE[key].default
        for key in PARTICIPANT_KEYS
    }


def limit_of(rules: Mapping[str, str]) -> int:
    """The most attempts a browser may start under "allow"; 0 for no limit."""
    if rules.get(REPEAT_ATTEMPTS) == "forbid":
        return 0
    return int(rules.get(MAX_ATTEMPTS, "0") or "0")


def needs_identity(rules: Mapping[str, str]) -> bool:
    return (
        rules.get(REPEAT_ATTEMPTS) == "forbid"
        or limit_of(rules) > 0
        or rules.get(AFTER_PASS, "more") == "stop"
        or rules.get(ASK_NAME, "off") != "off"
        or rules.get(ASK_EMAIL, "off") != "off"
    )


def needs_participant(run: QuizRun) -> bool:
    """Its own rules, a visible scoreboard that shows one row per browser (ADR-0051), or rewards,
    which go to a participant."""
    from app.domain import results, rewards  # they read this module's runs back

    return needs_identity(rules_of(run)) or results.needs_participant(run) or rewards.has_rules(run)


def cookie_name(run: QuizRun) -> str:
    return f"{COOKIE_PREFIX}{run.id.hex}"


def key_hash(run: QuizRun, key: str) -> str:
    """Only this is stored, so the same browser has a different hash in every run."""
    return salted_hmac("kvizotron.participant", f"{run.id}:{key}", algorithm="sha256").hexdigest()


def find(run: QuizRun, key: str) -> Participant | None:
    if not key:
        return None
    return Participant.objects.filter(run=run, anonymous_key_hash=key_hash(run, key)).first()


def _next_number(run: QuizRun) -> int:
    """The run's counter plus one. It never goes down, so an erased number never comes back.

    Call inside the transaction that creates the row: IMMEDIATE holds the write lock, so no two
    browsers get one number. A refused or rolled-back creation gives its number back with it.
    """
    QuizRun.all_kinds.filter(pk=run.pk).update(participant_seq=F("participant_seq") + 1)
    return QuizRun.all_kinds.values_list("participant_seq", flat=True).get(pk=run.pk)


def find_or_create(run: QuizRun, key: str) -> Participant:
    hashed = key_hash(run, key)
    found = Participant.objects.filter(run=run, anonymous_key_hash=hashed).first()
    if found is not None:
        return found
    try:
        with transaction.atomic():
            return Participant.objects.create(
                run=run, anonymous_key_hash=hashed, number=_next_number(run)
            )
    except IntegrityError:  # another tab of the same browser created it first
        return Participant.objects.get(run=run, anonymous_key_hash=hashed)


@dataclass(frozen=True)
class Begin:
    decision: StartDecision
    attempt: Attempt | None  # the open one, for `resume` and `replace`


def _open_attempt(participant: Participant) -> Attempt | None:
    """The attempt still in play, found at the end of any `replaced_by` chain."""
    related = ("run", "run__current_revision", "revision")
    current = (
        Attempt.objects.filter(
            participant=participant,
            status__in=(Attempt.Status.IN_PROGRESS, Attempt.Status.SWITCHED),
        )
        .select_related(*related)
        .order_by("-started_at", "-id")
        .first()
    )
    while current is not None and current.replaced_by_id is not None:
        current = Attempt.objects.select_related(*related).get(pk=current.replaced_by_id)
    if current is None or current.status != Attempt.Status.IN_PROGRESS:
        return None
    return current


def begin(run: QuizRun, participant: Participant | None) -> Begin:
    """What a start means for this participant. Call it inside the transaction that acts on it."""
    from app.domain import attempts  # attempts imports this module

    if participant is None:
        return Begin("new", None)
    policy = cast(ParticipantPolicyPlugin, registry.get("participant_policy", "basic"))
    open_attempt = _open_attempt(participant)
    state: OpenAttempt = "none"
    if open_attempt is not None:
        state = "expired" if attempts.time_left(open_attempt) == 0 else "running"
    finished = Attempt.objects.filter(participant=participant, status__in=Attempt.FINISHED).exists()
    rules = rules_of(run)
    used = _started(participant)
    if open_attempt is not None:
        used = used.exclude(pk=open_attempt.pk)
    passed = False
    if rules.get(AFTER_PASS, "more") == "stop":
        passed = results.kept_passed(results.kept(participant), run) is True
    decision = policy.on_start(
        rules, finished=finished, used=used.count(), passed=passed, open_attempt=state
    )
    return Begin(decision, open_attempt if decision in ("resume", "replace") else None)


def _started(participant: Participant) -> QuerySet[Attempt]:
    """Every attempt the participant began; a switched one only hands over to its successor."""
    return Attempt.objects.filter(participant=participant).exclude(status=Attempt.Status.SWITCHED)


def attempts_left(run: QuizRun, participant: Participant | None) -> int | None:
    """None without a limit; an attempt still open counts as begun."""
    limit = limit_of(rules_of(run))
    if limit == 0:
        return None
    if participant is None:
        return limit
    return max(0, limit - _started(participant).count())


def start_decision(run: QuizRun, participant: Participant | None) -> StartDecision:
    """What a start by this participant would be, without acting on it."""
    return begin(run, participant).decision


def can_resume(run: QuizRun, participant: Participant | None) -> bool:
    """Whether a start by this participant would pick up an attempt already begun."""
    begun = begin(run, participant)
    return begun.decision == "resume" and begun.attempt is not None


@dataclass(frozen=True)
class Identity:
    name: str  # as shown; "" when none
    email: str | None


@dataclass(frozen=True)
class Missing:
    name: bool
    email: bool

    def __bool__(self) -> bool:
        return self.name or self.email


def _policy() -> ParticipantPolicyPlugin:
    return cast(ParticipantPolicyPlugin, registry.get("participant_policy", "basic"))


def read_identity(
    rules: Mapping[str, str], raw_name: str, raw_email: str, *, automatic: bool
) -> Identity:
    """What the form gave. Automatic submission keeps the score whatever is wrong or missing."""
    from app.domain.attempts import AttemptError  # attempts imports this module

    policy = _policy()
    name = ""
    name_mode = rules.get(ASK_NAME, "off")
    if name_mode != "off":
        try:
            name = policy.clean_name(raw_name)
        except ValueError:
            if not automatic:
                raise AttemptError("name_too_long") from None
        if not name and name_mode == "required" and not automatic:
            raise AttemptError("name_required")
    email: str | None = None
    email_mode = rules.get(ASK_EMAIL, "off")
    if email_mode != "off":
        given = raw_email.strip()
        if given and policy.valid_email(given):
            email = given
        elif given and not automatic:
            raise AttemptError("email_invalid")
        elif not given and email_mode == "required" and not automatic:
            raise AttemptError("email_required")
    return Identity(name, email)


def name_is_taken(run: QuizRun, name: str, *, exclude: Participant | None = None) -> bool:
    """Only a participant with a finished attempt holds a name, and only when the run forbids it."""
    if not name or rules_of(run).get(DUPLICATE_NAMES) != "forbid":
        return False
    others = Participant.objects.filter(
        run=run,
        name_key=_policy().name_key(name),
        attempts__status__in=Attempt.FINISHED,
    )
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    return others.exists()


def email_key_of(email: str | None) -> str | None:
    """What an address is searched by: stripped and casefolded, None for none."""
    return (email or "").strip().casefold() or None


def claim_name(participant: Participant, identity: Identity, *, automatic: bool) -> None:
    """Call inside the transaction that stores the submission, so two cannot both win."""
    from app.domain.attempts import AttemptError  # attempts imports this module

    name = identity.name
    dropped = False
    if name_is_taken(participant.run, name, exclude=participant):
        if not automatic:
            raise AttemptError("name_taken")
        name, dropped = "", True
    if name:  # an empty value never erases what this participant gave before
        participant.display_name = name
        participant.name_key = _policy().name_key(name)
    participant.name_dropped = dropped and not participant.display_name
    if identity.email:
        participant.email = identity.email
        participant.email_key = email_key_of(identity.email)
    participant.save(
        update_fields=["display_name", "name_key", "email", "email_key", "name_dropped"]
    )


class NameRefused(Exception):
    """`code` is `empty`, `too_long` or `taken`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def rename(participant: Participant, name: str, *, admin_id: str) -> None:
    """An admin changes a nickname, for one that should not be on a scoreboard.

    The rules of the run hold as they do for the participant: a name another participant with a
    finished attempt holds is refused where the run forbids equal names. An empty name is
    refused, not an erasure, and `name_dropped` is left as it was. The audit entry has no name.
    """
    authoring.ensure_editable(participant.run.quiz)
    policy = _policy()
    try:
        clean = policy.clean_name(name)
    except ValueError:
        raise NameRefused("too_long") from None
    if not clean:
        raise NameRefused("empty")
    with transaction.atomic():
        if name_is_taken(participant.run, clean, exclude=participant):
            raise NameRefused("taken")
        participant.display_name = clean
        participant.name_key = policy.name_key(clean)
        participant.save(update_fields=["display_name", "name_key"])
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="participant.renamed",
            entity_type="participant",
            entity_id=str(participant.pk),
            details={},
        )
    results.clear_board_cache(participant.run_id)


def missing(participant: Participant | None) -> Missing:
    """What the result page still asks for: a required field that is empty, or a name left out."""
    if participant is None:
        return Missing(False, False)
    rules = rules_of(participant.run)
    return Missing(
        name=(rules.get(ASK_NAME, "off") == "required" and not participant.display_name)
        or (rules.get(ASK_NAME, "off") != "off" and participant.name_dropped),
        email=rules.get(ASK_EMAIL, "off") == "required" and not participant.email,
    )


@dataclass(frozen=True)
class AttemptRow:
    name: str  # "" when none was given
    email: str | None
    score: Decimal | None
    max_score: Decimal | None
    submitted_at: datetime
    duration_ms: int | None = None
    participant_id: UUID | None = None
    passed: bool | None = None  # this attempt against the run's pass mark; None while unjudged


ROW_SORTS = ("name", "score", "submitted", "duration")


def attempt_rows(
    run: QuizRun, sort: str = "submitted", descending: bool = False
) -> list[AttemptRow]:
    """One row per submitted attempt. For the logged-in administration only: it holds e-mails."""
    found = (
        Attempt.objects.filter(run=run, status__in=Attempt.FINISHED, submitted_at__isnull=False)
        .select_related("participant")
        .order_by("submitted_at", "id")
    )
    rows = []
    for attempt in found:
        attempt.run = run  # one run object, not one query per attempt
        who = attempt.participant
        rows.append(
            AttemptRow(
                who.display_name if who else "",
                (who.email or None) if who else None,
                attempt.score,
                attempt.max_score,
                attempt.submitted_at,  # type: ignore[arg-type]
                attempt.duration_ms,
                who.pk if who else None,
                results.attempt_passed(attempt),
            )
        )
    if sort not in ROW_SORTS:
        sort, descending = "submitted", False
    if sort == "submitted":
        return list(reversed(rows)) if descending else rows

    def value(row: AttemptRow) -> object:
        if sort == "name":
            return row.name.casefold() if row.name else None
        if sort == "score":
            return row.score
        return row.duration_ms

    present = [row for row in rows if value(row) is not None]
    missing = [row for row in rows if value(row) is None]
    present.sort(key=value, reverse=descending)  # type: ignore[arg-type]  # stable: ties by time
    return present + missing
