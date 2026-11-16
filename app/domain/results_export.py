"""What a run exports, file by file, under its data profile (FR-42, D2).

Only submitted attempts of normal runs are written: test runs and their test-link attempts, and
attempts nobody sent, never reach a file. A cell is always text already formatted for the admin's
language; answer keys, tokens and the access-code hash are never read here.
"""

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from django.db.models import QuerySet
from django.utils.text import slugify
from django.utils.translation import gettext_lazy, override

from app.contracts import ExportTable, QuestionTypePlugin
from app.domain import clock, data_policy, results, rewards, run_stats, selection, settings
from app.domain.models import (
    Attempt,
    AttemptAnswer,
    Draw,
    DrawEntry,
    Participant,
    Quiz,
    QuizRevision,
    QuizRun,
    RewardRule,
    RunRevision,
)
from app.kernel import audit, registry

__all__ = [
    "FILES",
    "PERSONAL",
    "file_name",
    "has_photos",
    "offered",
    "photo_files",
    "record_created",
    "record_downloaded",
    "runs_for",
    "tables",
]

FILES = ("attempts", "participants", "questions", "answers", "entitlements", "draws")
PERSONAL = frozenset(FILES) - {"questions"}
PHOTO_EXTENSION = "webp"  # the media provider stores every participant photo as WebP
_COMMA_LOCALES = ("cs", "uk")
_TENTH = Decimal("0.1")
_HUNDRED = Decimal(100)

_HEADERS = {
    "run": gettext_lazy("Run"),
    "revision": gettext_lazy("Revision"),
    "attempt_id": gettext_lazy("Attempt ID"),
    "participant_id": gettext_lazy("Participant ID"),
    "name": gettext_lazy("Name"),
    "email": gettext_lazy("E-mail address"),
    "status": gettext_lazy("Status"),
    "score": gettext_lazy("Score"),
    "max": gettext_lazy("Maximum"),
    "percent": gettext_lazy("Percent"),
    "submitted_at": gettext_lazy("Submitted at"),
    "official": gettext_lazy("Official"),
    "place": gettext_lazy("Place"),
    "duration": gettext_lazy("Duration (s)"),
    "attempts": gettext_lazy("Attempts"),
    "best_score": gettext_lazy("Best score"),
    "kept_percent": gettext_lazy("Kept score (%)"),
    "passed": gettext_lazy("Passed"),
    "submitted": gettext_lazy("Submitted attempts"),
    "question_no": gettext_lazy("Question no."),
    "question": gettext_lazy("Question"),
    "type": gettext_lazy("Type"),
    "answered": gettext_lazy("Answered"),
    "correct_share": gettext_lazy("Full points (%)"),
    "average": gettext_lazy("Average points"),
    "answer": gettext_lazy("Answer"),
    "points": gettext_lazy("Points"),
    "graded_by": gettext_lazy("Graded by"),
    "rule": gettext_lazy("Rule"),
    "reward": gettext_lazy("Reward"),
    "reason": gettext_lazy("Reason"),
    "state": gettext_lazy("State"),
    "handed_over_at": gettext_lazy("Handed over at"),
    "cancel_reason": gettext_lazy("Cancel reason"),
    "draw_no": gettext_lazy("Draw no."),
    "kind": gettext_lazy("Kind"),
    "at": gettext_lazy("At"),
    "admin": gettext_lazy("Admin"),
    "eligible": gettext_lazy("Eligible"),
    "fingerprint": gettext_lazy("Fingerprint"),
    "winners": gettext_lazy("Winners"),
    "alternates": gettext_lazy("Alternates"),
}
_LABELS = {
    Attempt.Status.SUBMITTED: gettext_lazy("submitted"),
    Attempt.Status.PENDING_GRADING: gettext_lazy("waiting for grading"),
    "yes": gettext_lazy("yes"),
    "no": gettext_lazy("no"),
    "auto": gettext_lazy("automatic"),
    "admin": gettext_lazy("admin"),
    "photo": gettext_lazy("photo"),
    "removed": gettext_lazy("removed"),
    "threshold": gettext_lazy("threshold"),
    "participation": gettext_lazy("participation"),
    "manual": gettext_lazy("manual"),
    "draw": gettext_lazy("draw"),
    "granted": gettext_lazy("granted"),
    "handed_over": gettext_lazy("handed over"),
    "cancelled": gettext_lazy("cancelled"),
    "redraw": gettext_lazy("redraw"),
    "move_up": gettext_lazy("move up"),
    "substitute": gettext_lazy("substitute"),
}
_COLUMNS = {
    "attempts": (
        "attempt_id",
        "participant_id",
        "name",
        "status",
        "score",
        "max",
        "percent",
        "submitted_at",
        "official",
        "place",
        "passed",
    ),
    "participants": (
        "participant_id",
        "name",
        "email",
        "attempts",
        "best_score",
        "kept_percent",
        "passed",
    ),
    "questions": (
        "submitted",
        "question_no",
        "question",
        "type",
        "answered",
        "correct_share",
        "average",
        "max",
    ),
    "answers": ("attempt_id", "question_no", "question", "answer", "points", "max", "graded_by"),
    "entitlements": (
        "rule",
        "reward",
        "participant_id",
        "name",
        "email",
        "reason",
        "state",
        "handed_over_at",
        "cancel_reason",
    ),
    "draws": (
        "rule",
        "reward",
        "draw_no",
        "kind",
        "at",
        "admin",
        "eligible",
        "fingerprint",
        "winners",
        "alternates",
        "reason",
    ),
}
_NUMERIC = frozenset(
    {
        "run",
        "revision",
        "score",
        "max",
        "percent",
        "place",
        "duration",
        "attempts",
        "best_score",
        "kept_percent",
        "submitted",
        "question_no",
        "answered",
        "correct_share",
        "average",
        "points",
        "rule",
        "draw_no",
        "eligible",
    }
)

Row = dict[str, str]


# Which runs and which files


def runs_for(quiz: Quiz, run_ids: Sequence[str] | None) -> list[QuizRun]:
    """Normal runs of this quiz only. An unknown, foreign or test run raises `DoesNotExist`."""
    found = QuizRun.objects.filter(quiz=quiz).select_related("quiz", "current_revision")
    if run_ids is None:
        return list(found.order_by("run_no"))
    try:
        wanted = {uuid.UUID(str(value)) for value in run_ids}
    except ValueError:
        raise QuizRun.DoesNotExist from None
    runs = list(found.filter(pk__in=wanted).order_by("run_no"))
    if len(runs) != len(wanted):
        raise QuizRun.DoesNotExist
    return runs


def _profile(run: QuizRun) -> str:
    return data_policy.of(run)[data_policy.PROFILE]


def _finished(run: QuizRun) -> QuerySet[Attempt]:
    return Attempt.objects.filter(run=run, status__in=Attempt.FINISHED, submitted_at__isnull=False)


def _kept_answers(runs: Iterable[QuizRun]) -> QuerySet[AttemptAnswer]:
    return AttemptAnswer.objects.filter(
        attempt__run__in=list(runs),
        attempt__status__in=Attempt.FINISHED,
        attempt__submitted_at__isnull=False,
    )


def _provides(run: QuizRun, name: str) -> bool:
    profile = _profile(run)
    if data_policy.is_stateless(profile):
        return name == "questions"
    if name == "answers":
        return data_policy.keeps_all_answers(profile) or any(
            data_policy.has_photo_question(revision.snapshot_json) for revision in _revisions(run)
        )
    if name == "entitlements":
        return RewardRule.objects.filter(run=run).exists()
    if name == "draws":
        return RewardRule.objects.filter(run=run, kind=RewardRule.Kind.DRAW).exists()
    return True


def offered(runs: Sequence[QuizRun]) -> dict[str, int]:
    """How many of the runs give each file; a file no run gives is left out."""
    counts = {name: sum(1 for run in runs if _provides(run, name)) for name in FILES}
    return {name: count for name, count in counts.items() if count}


def has_photos(runs: Sequence[QuizRun]) -> bool:
    return _kept_answers(runs).filter(asset_id__isnull=False, removed=False).exists()


# Formatting


def _number(value: Decimal | int | None, locale: str) -> str:
    if value is None:
        return ""
    text = format(Decimal(value).normalize(), "f")
    return text.replace(".", ",") if locale in _COMMA_LOCALES else text


def _percent(score: Decimal | None, top: Decimal | None) -> Decimal | None:
    if score is None or not top:
        return None
    return (score / top * _HUNDRED).quantize(_TENTH, ROUND_HALF_UP)


def _label(key: object) -> str:
    found = _LABELS.get(str(key))
    return str(found) if found is not None else str(key)


def _verdict(passed: bool | None) -> str:
    return "" if passed is None else _label("yes" if passed else "no")


def _revisions(run: QuizRun) -> list[QuizRevision]:
    """What the run used, oldest first; a planned run has only its current one."""
    rows = RunRevision.objects.filter(run=run).select_related("revision").order_by("active_from")
    seen: dict[object, QuizRevision] = {}
    for row in rows:
        seen.setdefault(row.revision_id, row.revision)
    return list(seen.values()) or [run.current_revision]


class _Questions:
    """Questions of each revision by id, with their number in the revision, 1-based."""

    def __init__(self, quiz: Quiz, locale: str) -> None:
        self.quiz = quiz
        self.locale = locale
        self._by_revision: dict[object, dict[str, tuple[int, Mapping[str, Any]]]] = {}

    def of(self, revision: QuizRevision) -> dict[str, tuple[int, Mapping[str, Any]]]:
        if revision.pk not in self._by_revision:
            self._by_revision[revision.pk] = {
                question["id"]: (number, question)
                for number, question in enumerate(
                    selection.all_questions(revision.snapshot_json), start=1
                )
            }
        return self._by_revision[revision.pk]

    def text(self, question: Mapping[str, Any]) -> str:
        try:
            plugin = _plugin(question)
            for code in (self.locale, self.quiz.default_locale):
                prompt = plugin.public_payload(question["definition"], code).get("prompt")
                if prompt:
                    return str(prompt)
        except LookupError, TypeError, ValueError, AttributeError:
            pass
        return str(question["type"])


def _plugin(question: Mapping[str, Any]) -> QuestionTypePlugin:
    return cast(
        QuestionTypePlugin,
        registry.get("question_type", question["type"], include_disabled=True),
    )


# Files


def _attempts(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    """Place as the admin board shows it, whatever the public sees; official as rewards see it.

    The admin board keeps the run's revision mode, so a separate table ranks its own attempts and
    an official attempt on an older revision under `latest` has no place. A shared board of several
    runs never counts: the place is the one in the run's own board (ADR-0065).
    """
    del questions
    ranked = {
        row.attempt_id: row.rank
        for table in results.board(run, audience="admin", locale=locale, own_run=True).tables
        for row in table.rows
    }
    official: dict[object, object] = {}  # participant -> the chosen attempt id, or None
    averaged: set[object] = set()  # participants whose every submitted attempt is in the mean
    rows = []
    for attempt in (
        _finished(run).select_related("participant", "revision").order_by("submitted_at", "id")
    ):
        attempt.run = run
        who = attempt.participant
        place = ranked.get(str(attempt.id))
        if who is None:  # an attempt without a browser counts on its own
            counts = attempt.status == Attempt.Status.SUBMITTED and attempt.score is not None
        else:
            if who.pk not in official:
                found = results.kept(who)
                if found is None:
                    official[who.pk] = None
                else:
                    official[who.pk] = found.attempt.pk
                    if found.rule == "average":
                        averaged.add(who.pk)
            counts = official[who.pk] == attempt.pk or (
                who.pk in averaged
                and attempt.status == Attempt.Status.SUBMITTED
                and attempt.score is not None
            )
        rows.append(
            {
                "revision": str(attempt.revision.revision_no),
                "attempt_id": str(attempt.id),
                "participant_id": str(who.id) if who else "",
                "name": who.display_name if who else "",
                "status": _label(attempt.status),
                "score": _number(attempt.score, locale),
                "max": _number(attempt.max_score, locale),
                "percent": _number(_percent(attempt.score, attempt.max_score), locale),
                "submitted_at": clock.iso(attempt.submitted_at),
                "official": _label("yes" if counts else "no"),
                "place": str(place) if place is not None else "",
                "passed": _verdict(results.attempt_passed(attempt)),
                "duration": _number(
                    None if attempt.duration_ms is None else Decimal(attempt.duration_ms) / 1000,
                    locale,
                ),
            }
        )
    return rows


def _participants(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    del questions
    by_person: dict[object, list[Attempt]] = {}
    for attempt in _finished(run).select_related("revision").order_by("submitted_at", "id"):
        if attempt.participant_id:
            by_person.setdefault(attempt.participant_id, []).append(attempt)
    rows = []
    for who in Participant.objects.filter(pk__in=by_person).order_by("created_at", "id"):
        mine = by_person[who.pk]
        scored = [a for a in mine if a.score is not None]
        best = max(scored, key=lambda a: cast(Decimal, a.score)) if scored else mine[-1]
        kept = results.kept(who)
        kept_percent = (
            _percent(kept.figures.score, kept.figures.max_score) if kept is not None else None
        )
        rows.append(
            {
                "revision": str(best.revision.revision_no),
                "participant_id": str(who.id),
                "name": who.display_name,
                "email": who.email or "",
                "attempts": str(len(mine)),
                "best_score": _number(best.score, locale),
                "kept_percent": _number(kept_percent, locale),
                "passed": _verdict(results.kept_passed(kept, run)),
            }
        )
    return rows


def _questions(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    if data_policy.is_stateless(_profile(run)):
        revision = str(run.current_revision.revision_no)  # AC-108: every row names one
        return [{"revision": revision, "submitted": str(run.stateless_submitted)}]
    rows = []
    for revision in _revisions(run):
        submitted, stats = run_stats.of_revision(run, revision.pk)
        for question_id, (number, question) in questions.of(revision).items():
            stat = stats.get(question_id)
            rows.append(
                {
                    "revision": str(revision.revision_no),
                    "submitted": str(submitted),
                    "question_no": str(number),
                    "question": questions.text(question),
                    "type": str(question["type"]),
                    "answered": str(stat.answered) if stat else "",
                    "correct_share": str(stat.full_share) if stat else "",
                    "average": _number(stat.average, locale) if stat else "",
                    "max": _number(run_stats.question_max(question), locale),
                }
            )
    return rows


def _photo_path(run: QuizRun, attempt_id: object, number: int) -> str:
    return f"photos/{run.run_no}/{attempt_id}-{number}.{PHOTO_EXTENSION}"


def _answer_text(
    row: AttemptAnswer, question: Mapping[str, Any], number: int, run: QuizRun, known: _Questions
) -> str:
    """Words, not JSON: the question type says what was answered. A photo names its file."""
    if row.removed:
        return _label("removed")
    try:
        plugin = _plugin(question)
    except LookupError:
        return ""
    definition = question["definition"]
    if plugin.file_fields(definition):
        if not row.asset_id:
            return ""
        return f"{_label('photo')}: {_photo_path(run, row.attempt_id, number)}"
    for code in (known.locale, known.quiz.default_locale):
        labels = [item.label for item in plugin.summarize(definition, [row.answer_json], code)]
        if any(labels):
            return ", ".join(labels)
    return ""


def _answers(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    rows = []
    found = (
        _kept_answers([run])
        .select_related("attempt", "attempt__revision")
        .order_by("attempt__submitted_at", "attempt_id")
    )
    for answer in found:
        revision = answer.attempt.revision
        known = questions.of(revision).get(answer.question_id)
        if known is None:
            continue
        number, question = known
        rows.append(
            {
                "revision": str(revision.revision_no),
                "attempt_id": str(answer.attempt_id),
                "question_no": str(number),
                "question": questions.text(question),
                "answer": _answer_text(answer, question, number, run, questions),
                "points": _number(answer.auto_points + (answer.manual_points or 0), locale),
                "max": _number(run_stats.question_max(question), locale),
                "graded_by": _label("admin" if answer.graded_by else "auto"),
            }
        )
    rows.sort(key=lambda row: (row["attempt_id"], int(row["question_no"])))
    return rows


def _rule_numbers(run: QuizRun) -> dict[object, int]:
    return {rule.pk: number for number, rule in enumerate(rewards.rules_of(run), start=1)}


def _entitlements(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    del locale
    numbers = _rule_numbers(run)
    rows = []
    for row in rewards.of_run(run):
        who = row.participant
        revision = row.attempt.revision if row.attempt else run.current_revision
        status = row.status
        rows.append(
            {
                "revision": str(revision.revision_no),
                "rule": str(numbers.get(row.rule_id, "")),
                "reward": rewards.text(row.rule, questions.quiz, questions.locale, "name"),
                "participant_id": str(who.id),
                "name": who.display_name,
                "email": who.email or "",
                "reason": _label(row.rule.kind),
                "state": _label(status),
                "handed_over_at": clock.iso(row.changed_at)
                if status == row.Status.HANDED_OVER
                else "",
                "cancel_reason": row.reason if status == row.Status.CANCELLED else "",
            }
        )
    return rows


def _entry(entry: DrawEntry) -> str:
    """Nickname and participant id; the pseudonym once the participant is gone. Never an e-mail."""
    who = entry.participant
    if who is None:
        return entry.pseudonym
    return f"{who.display_name} ({who.id})" if who.display_name else f"({who.id})"


def _draws(run: QuizRun, locale: str, questions: _Questions) -> list[Row]:
    del locale
    numbers = _rule_numbers(run)
    counter: dict[object, int] = {}
    rows = []
    found = (
        Draw.objects.filter(run=run)
        .select_related("rule")
        .prefetch_related("entries__participant")
        .order_by("created_at", "id")
    )
    for draw in found:
        counter[draw.rule_id] = counter.get(draw.rule_id, 0) + 1
        entries = sorted(draw.entries.all(), key=lambda entry: entry.position)
        rows.append(
            {
                "revision": str(run.current_revision.revision_no),
                "rule": str(numbers.get(draw.rule_id, "")),
                "reward": rewards.text(draw.rule, questions.quiz, questions.locale, "name"),
                "draw_no": str(counter[draw.rule_id]),
                "kind": _label(draw.action),
                "at": clock.iso(draw.created_at),
                "admin": draw.admin_id,
                "eligible": str(draw.eligible_count),
                "fingerprint": draw.eligible_set_hash,
                "winners": ", ".join(
                    _entry(entry) for entry in entries if entry.role == DrawEntry.Role.WINNER
                ),
                "alternates": ", ".join(
                    _entry(entry) for entry in entries if entry.role == DrawEntry.Role.ALTERNATE
                ),
                "reason": draw.reason,
            }
        )
    return rows


_BUILD: dict[str, Callable[[QuizRun, str, _Questions], list[Row]]] = {
    "attempts": _attempts,
    "participants": _participants,
    "questions": _questions,
    "answers": _answers,
    "entitlements": _entitlements,
    "draws": _draws,
}


def _columns(name: str, runs: Sequence[QuizRun]) -> tuple[str, ...]:
    columns = ("run", "revision", *_COLUMNS[name])
    if name == "attempts" and any(
        data_policy.keeps_duration(_profile(run)) for run in runs if _provides(run, name)
    ):
        columns += ("duration",)
    return columns


def tables(
    runs: Sequence[QuizRun], files: Sequence[str], locale: str, *, photos: bool
) -> list[ExportTable]:
    """One table per file, rows of every run that gives it, headers in `locale`.

    An answer names its photo by its path in the ZIP whether or not the photos go with it, so a
    later export with photos matches the same file.
    """
    del photos
    found = []
    with override(locale):
        for name in (name for name in FILES if name in files):
            columns = _columns(name, runs)
            rows: list[Row] = []
            for run in runs:
                if not _provides(run, name):
                    continue
                questions = _Questions(run.quiz, locale)
                for row in _BUILD[name](run, locale, questions):
                    full = {"run": str(run.run_no)} | row
                    rows.append({column: full.get(column, "") for column in columns})
            found.append(
                ExportTable(
                    name=name,
                    columns=columns,
                    headers=[str(_HEADERS[column]) for column in columns],
                    rows=rows,
                    numeric=_NUMERIC & frozenset(columns),
                )
            )
    return found


def photo_files(runs: Sequence[QuizRun]) -> dict[str, str]:
    """Path in the ZIP -> asset id, for every photo a submitted attempt keeps."""
    found: dict[str, str] = {}
    numbers: dict[object, dict[str, int]] = {}
    by_id = {run.pk: run for run in runs}
    rows = (
        _kept_answers(runs)
        .filter(asset_id__isnull=False, removed=False)
        .select_related("attempt", "attempt__revision")
    )
    for answer in rows:
        revision = answer.attempt.revision
        if revision.pk not in numbers:
            numbers[revision.pk] = {
                question["id"]: number
                for number, question in enumerate(
                    selection.all_questions(revision.snapshot_json), start=1
                )
            }
        number = numbers[revision.pk].get(answer.question_id)
        if number is None:
            continue
        run = by_id[answer.attempt.run_id]
        found[_photo_path(run, answer.attempt_id, number)] = cast(str, answer.asset_id)
    return found


# Audit and names


def record_created(job_id: str, admin_id: str, choices: Mapping[str, Any]) -> None:
    """Which runs and files, never a value from them. Photos count as personal data."""
    files = [str(name) for name in choices.get("files") or []]
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="export.created",
        entity_type="export_job",
        entity_id=job_id,
        details={
            "quiz": str(choices.get("quiz") or ""),
            "runs": [str(run) for run in choices.get("runs") or []],
            "all_runs": bool(choices.get("all_runs")),
            "files": files,
            "photos": bool(choices.get("photos")),
            "personal": bool(PERSONAL & set(files)) or bool(choices.get("photos")),
        },
    )


def record_downloaded(job_id: str, admin_id: str, name: str) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action="export.downloaded",
        entity_type="export_job",
        entity_id=job_id,
        details={"name": name},
    )


def file_name(quiz: Quiz, runs: Sequence[QuizRun], all_runs: bool, at: datetime) -> str:
    """`<slug>-<run-N|all|runs>-<YYYYMMDD-HHMM>`: letters, digits, `.`, `_` and `-` only."""
    slug = slugify(quiz.slug).strip("-_.") or "quiz"
    if all_runs:
        which = "all"
    elif len(runs) == 1:
        which = f"run-{runs[0].run_no}"
    else:
        which = "runs"
    return f"{slug}-{which}-{at.astimezone(settings.zone()).strftime('%Y%m%d-%H%M')}"
