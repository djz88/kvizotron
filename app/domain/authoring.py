"""Editing a draft, publishing it as an immutable revision, opening and closing runs."""

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, cast

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext

from app.contracts import IMAGE_MODE_COPY, JSON, QuestionTypePlugin, ScoringStrategyPlugin
from app.domain import (
    bank_folders,
    banks,
    data_policy,
    participants,
    requirements,
    selection,
    settings,
)
from app.domain import questions as question_rules
from app.domain import results as run_results
from app.domain import rewards as run_rewards
from app.domain.models import (
    AppSetting,
    BankFolder,
    QuestionBank,
    Quiz,
    QuizRevision,
    QuizRun,
    RunRevision,
)
from app.kernel import audit, events, registry


class Decision(StrEnum):
    """What the admin chooses at publication, when the policy leaves it to them."""

    NOTIFY_SWITCH = "notify_switch"
    LET_FINISH = "let_finish"
    STAY = "stay"


class AuthoringError(Exception):
    pass


class DrawNotFound(AuthoringError):
    pass


class QuestionNotFound(AuthoringError):
    pass


class UnknownQuestionType(AuthoringError):
    pass


class NothingPublished(AuthoringError):
    pass


class RunAlreadyOpen(AuthoringError):
    pass


class RoundDecisionRequired(AuthoringError):
    pass


class NothingToDiscard(AuthoringError):
    pass


class NeverPublished(AuthoringError):
    """There is nothing to return to."""


class QuizArchived(AuthoringError):
    """An archived quiz is read-only until it is restored."""


class RunStillOpen(AuthoringError):
    pass


class SlugTaken(AuthoringError):
    pass


class RequirementUnmet(AuthoringError):
    """A module of the published content cannot work with a setting of this quiz."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class StalePublication(AuthoringError):
    """The quiz changed after the admin saw what they were about to publish."""


@dataclass(frozen=True)
class Problem:
    question_no: int | None
    locale: str | None
    # no_questions, no_changes, title_missing, description_missing, type_unavailable, invalid
    code: str
    detail: str = ""


class PublicationError(AuthoringError):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} problems block publication")
        self.problems = problems


def _question_type(type_id: str) -> QuestionTypePlugin:
    return cast(QuestionTypePlugin, registry.get("question_type", type_id))


def _scoring(strategy_id: str, **kwargs: Any) -> ScoringStrategyPlugin:
    return cast(ScoringStrategyPlugin, registry.get("scoring_strategy", strategy_id, **kwargs))


def latest_published(quiz: Quiz) -> QuizRevision | None:
    return quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).first()


def _current_draft(quiz: Quiz) -> QuizRevision | None:
    return quiz.revisions.filter(status=QuizRevision.Status.DRAFT).first()


def ensure_editable(quiz: Quiz) -> None:
    """Asks the database, because the object in hand may be older than the archiving."""
    if Quiz.objects.filter(pk=quiz.pk, archived_at__isnull=False).exists():
        raise QuizArchived(str(quiz.id))


def get_draft(quiz: Quiz) -> QuizRevision:
    """The quiz's draft; created from the latest published revision when there is none."""
    ensure_editable(quiz)
    draft = _current_draft(quiz)
    if draft is not None:
        return draft
    published = latest_published(quiz)
    questions = published.snapshot_json["questions"] if published else []
    draws = _rows_of(published.snapshot_json) if published else []
    last = quiz.revisions.aggregate(last=Max("revision_no"))["last"] or 0
    try:
        with transaction.atomic():
            return QuizRevision.objects.create(
                quiz=quiz,
                revision_no=last + 1,
                snapshot_json={"questions": questions, "draws": draws},
            )
    except IntegrityError:  # another admin started the draft at the same moment
        draft = _current_draft(quiz)
        if draft is None:
            raise
        return draft


def has_draft(quiz: Quiz) -> bool:
    return _current_draft(quiz) is not None


def _rows_of(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Draw rows as a draft holds them: a pool exists only from publication on."""
    return [
        {key: value for key, value in row.items() if key != "pool"}
        for row in snapshot.get("draws", [])
    ]


def editable_draws(quiz: Quiz) -> list[dict[str, Any]]:
    revision = _current_draft(quiz) or latest_published(quiz) or _latest_archived(quiz)
    return _rows_of(revision.snapshot_json) if revision else []


def save_draw(
    quiz: Quiz,
    draw_id: str | None,
    *,
    bank_id: str,
    tag: str,
    count: int,
    points: int,
    position: int,
    folder_id: str = "",
    difficulty: str = "",
) -> str:
    if difficulty and difficulty not in banks.LEVELS:
        raise ValueError(difficulty)
    bank = QuestionBank.objects.get(pk=bank_id)
    folder = None
    if folder_id:
        folder = BankFolder.objects.filter(pk=folder_id, bank=bank).first()
        if folder is None:
            raise bank_folders.WrongBank(gettext("The folder is not in this bank."))
    with transaction.atomic():
        draft = get_draft(quiz)
        draws = draft.snapshot_json.setdefault("draws", [])
        if draw_id is None:
            row: dict[str, Any] = {"id": str(uuid.uuid7())}
            draws.append(row)
        else:
            row = _find_draw(draws, draw_id)
        row.update(
            bank_id=str(bank.id),
            bank_name=bank.name,
            tag=tag.strip(),
            folder_id=str(folder.pk) if folder else "",
            folder_path=bank_folders.path_of(folder),
            difficulty=difficulty,
            count=count,
            points=points,
            position=position,
        )
        draft.save()
    return row["id"]


def delete_draw(quiz: Quiz, draw_id: str) -> None:
    with transaction.atomic():
        draft = get_draft(quiz)
        draws = draft.snapshot_json.setdefault("draws", [])
        draws.remove(_find_draw(draws, draw_id))
        draft.save()


def _find_draw(draws: list[dict[str, Any]], draw_id: str) -> dict[str, Any]:
    for row in draws:
        if row["id"] == draw_id:
            return row
    raise DrawNotFound(draw_id)


def _pool_content(pool: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The version stamp comes with publication and says nothing about the question."""
    return [{k: v for k, v in q.items() if k != "scoring_version"} for q in pool]


def banks_changed(quiz: Quiz) -> bool:
    """Would a publication now copy something else than the published revision holds?"""
    published = latest_published(quiz)
    if published is None:
        return False
    return any(
        _pool_content(row["pool"]) != banks.pool(row, quiz.supported_locales)
        for row in published.snapshot_json.get("draws", [])
    )


def has_changes(quiz: Quiz) -> bool:
    return has_draft(quiz) or banks_changed(quiz)


def editable_questions(quiz: Quiz) -> list[dict[str, Any]]:
    revision = _current_draft(quiz) or latest_published(quiz) or _latest_archived(quiz)
    return list(revision.snapshot_json["questions"]) if revision else []


def _latest_archived(quiz: Quiz) -> QuizRevision | None:
    return (
        quiz.revisions.filter(status=QuizRevision.Status.ARCHIVED).order_by("-revision_no").first()
    )


def _new_question(plugin: QuestionTypePlugin, question_id: str | None = None) -> dict[str, Any]:
    return {
        "id": question_id or str(uuid.uuid7()),
        "scoring": plugin.available_scoring_strategies()[0],
        "settings": {"points": question_rules.DEFAULT_POINTS},
        "sources": [],
        "explanation": {},
    }


def add_questions(quiz: Quiz, items: Sequence[Mapping[str, Any]]) -> None:
    """Many at once, with the draft written once: a large import must not hold the write lock.

    Each item has `type_id` and `config`, and what `save_question` takes by keyword.
    """
    with transaction.atomic():
        draft = get_draft(quiz)
        for item in items:
            fields = dict(item)
            type_id = fields.pop("type_id")
            config = fields.pop("config")
            try:
                plugin = _question_type(type_id)
            except LookupError as exc:
                raise UnknownQuestionType(type_id) from exc
            question = _new_question(plugin)
            question_rules.apply_fields(question, plugin, config, **fields)
            draft.snapshot_json["questions"].append(question)
        draft.save()


def save_question(
    quiz: Quiz,
    question_id: str | None,
    type_id: str,
    config: JSON,
    *,
    points: int | None = None,
    scoring: str | None = None,
    sources: Sequence[str] | None = None,
    explanation: Mapping[str, str] | None = None,
    new_id: str | None = None,
    setting_values: Mapping[str, str] | None = None,
) -> str:
    """Store a question in the draft. It may be incomplete; publication validates it.

    What is left out stays as it was. A second save under the same `new_id` updates that question,
    so a double click cannot create two, and going back to fix the form keeps the fix. The write
    lock makes that hold for parallel requests.
    """
    try:
        plugin = _question_type(type_id)
    except LookupError as exc:
        raise UnknownQuestionType(type_id) from exc
    with transaction.atomic():
        draft = get_draft(quiz)
        questions = draft.snapshot_json["questions"]
        if question_id is None and new_id is not None and any(q["id"] == new_id for q in questions):
            question_id = new_id
        if question_id is None:
            question: dict[str, Any] = _new_question(plugin, new_id)
            questions.append(question)
        else:
            question = _find(questions, question_id)
        question_rules.apply_fields(
            question,
            plugin,
            config,
            points=points,
            scoring=scoring,
            sources=sources,
            explanation=explanation,
            setting_values=setting_values,
        )
        draft.save()
    return question["id"]


def delete_question(quiz: Quiz, question_id: str) -> None:
    with transaction.atomic():
        draft = get_draft(quiz)
        questions = draft.snapshot_json["questions"]
        index = questions.index(_find(questions, question_id))
        questions.pop(index)
        for row in draft.snapshot_json.get("draws", []):
            if row["position"] > index:
                row["position"] -= 1
        draft.save()


def _find(questions: list[dict[str, Any]], question_id: str) -> dict[str, Any]:
    for question in questions:
        if question["id"] == question_id:
            return question
    raise QuestionNotFound(question_id)


def validate_for_publication(quiz: Quiz) -> list[Problem]:
    questions = editable_questions(quiz)
    problems = [
        Problem(None, locale, "title_missing")
        for locale in quiz.supported_locales
        if not str(quiz.title.get(locale, "")).strip()
    ]
    problems += [
        Problem(None, locale, "description_missing")
        for locale in quiz.supported_locales
        if not str(quiz.description.get(locale, "")).strip()
    ]
    draws = editable_draws(quiz)
    if not questions and not draws:
        problems.append(Problem(None, None, "no_questions"))
    for number, question in enumerate(questions, start=1):
        problems += _question_problems(number, question, quiz.supported_locales)
        if _shows_a_missing_copy(quiz, question):
            problems.append(Problem(number, None, "image_no_copy"))
    return problems + _draw_problems(draws, quiz) + _requirement_problems(quiz)


def _requirement_problems(quiz: Quiz) -> list[Problem]:
    needed = requirements.of_quiz(quiz)
    found = [
        Problem(None, None, "requirement", item.text) for item in requirements.unmet(quiz, needed)
    ]
    clash = requirements.contradiction(needed)
    if clash is not None:
        detail = f"{clash[0].text} / {clash[1].text}"
        found.append(Problem(None, None, "requirement_conflict", detail))
    return found


def _row_label(row: Mapping[str, Any]) -> str:
    parts = [
        part
        for part in (
            row.get("folder_path"),
            row.get("tag"),
            banks.level_label(row.get("difficulty", "")),
        )
        if part
    ]
    return f"{row['bank_name']} ({' · '.join(parts)})" if parts else row["bank_name"]


def _shows_a_missing_copy(quiz: Quiz, question: Mapping[str, Any]) -> bool:
    """Only this quiz's mode tells, and a bank question may be used under several (ADR-0043)."""
    return settings.image_mode(
        quiz, question
    ) == IMAGE_MODE_COPY and question_rules.has_image_without_copy(question)


def _draw_problems(draws: Sequence[Mapping[str, Any]], quiz: Quiz) -> list[Problem]:
    """Rows are tried together, because they may share questions. The first misfit is named."""
    locales = quiz.supported_locales
    missing = [row for row in draws if not banks.exists(row["bank_id"])]
    if missing:
        return [Problem(None, None, "draw_bank_missing", _row_label(row)) for row in missing]
    filled: list[dict[str, Any]] = []
    for row in draws:
        filled.append({**row, "pool": banks.pool(row, locales)})
        if selection.assign(filled) is None:
            return [Problem(None, None, "draw_not_enough", _row_label(row))]
    return [
        Problem(None, None, "draw_image_no_copy", _row_label(row))
        for row in filled
        if any(_shows_a_missing_copy(quiz, question) for question in row["pool"])
    ]


def _question_problems(number: int, question: Mapping, locales: list[str]) -> list[Problem]:
    try:
        plugin = _question_type(question["type"])
        _scoring(question["scoring"])
    except LookupError as exc:
        return [Problem(number, None, "type_unavailable", str(exc))]
    problems = []
    for locale in locales:
        try:
            plugin.validate_definition(question["definition"], locale)
        except ValueError as exc:
            problems.append(Problem(number, locale, "invalid", str(exc)))
    problems += [
        Problem(number, locale, "explanation_missing")
        for locale in question_rules.explanation_gaps(question, locales)
    ]
    return problems


def round_outcome(quiz: Quiz) -> str | None:
    """None without an open round, otherwise the policy that applies to it."""
    if _open_round(quiz) is None:
        return None
    return settings.resolve(settings.REVISION_SWITCH_POLICY, quiz)


def _is_stateless(run: QuizRun) -> bool:
    return data_policy.is_stateless(data_policy.of(run)[data_policy.PROFILE])


def stateless_held_back(quiz: Quiz) -> bool:
    """A running stateless run kept its revision because the newest one has a photo question."""
    run = _open_round(quiz)
    latest = latest_published(quiz)
    return bool(
        run is not None
        and latest is not None
        and run.current_revision_id != latest.id
        and _is_stateless(run)
        and data_policy.has_photo_question(latest.snapshot_json)
    )


def _open_round(quiz: Quiz) -> QuizRun | None:
    return quiz.runs.filter(status=QuizRun.Status.OPEN).first()


def _round_decision(quiz: Quiz, decision: str | None) -> str:
    """A decision counts only when the policy asks for one."""
    outcome = settings.resolve(settings.REVISION_SWITCH_POLICY, quiz)
    if outcome != settings.Policy.ASK:
        return outcome
    if decision is None or decision not in set(Decision):
        raise RoundDecisionRequired(str(quiz.id))
    return decision


def _move_round(run: QuizRun, revision: QuizRevision, decision: str) -> None:
    """`stay` changes nothing, including what earlier decisions said about older attempts."""
    if decision == Decision.STAY:
        return
    now = timezone.now()
    run.revision_rows.filter(active_to__isnull=True).update(active_to=now)
    RunRevision.objects.create(
        run=run,
        revision=revision,
        active_from=now,
        max_score=revision.max_score,
        switch_mode=(
            RunRevision.SwitchMode.SWITCH
            if decision == Decision.NOTIFY_SWITCH
            else RunRevision.SwitchMode.FINISH
        ),
    )
    QuizRun.objects.filter(pk=run.pk).update(current_revision=revision)


def future_snapshot(quiz: Quiz) -> dict[str, Any]:
    """What publication would store now."""
    return {
        "title": quiz.title,
        "description": quiz.description,
        "default_locale": quiz.default_locale,
        "locales": quiz.supported_locales,
        "questions": editable_questions(quiz),
        "draws": [
            {**row, "pool": banks.pool(row, quiz.supported_locales)} for row in editable_draws(quiz)
        ],
    }


def future_summary(quiz: Quiz) -> dict[str, Any]:
    """Counts for a first publication: questions (draws count as their `count`), points."""
    snapshot = future_snapshot(quiz)
    points = Decimal(0)
    for question in snapshot["questions"]:
        points += _scoring(question["scoring"], include_disabled=True).max_score(
            question["settings"]
        )
    count = len(snapshot["questions"])
    for row in snapshot["draws"]:
        count += row["count"]
        if row["pool"]:
            first = row["pool"][0]
            strategy = _scoring(first["scoring"], include_disabled=True)
            points += strategy.max_score(first["settings"]) * row["count"]
    return {"questions": count, "points": points.normalize(), "locales": snapshot["locales"]}


def _canonical_hash(snapshot: Mapping[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def snapshot_hash(quiz: Quiz) -> str:
    return _canonical_hash(future_snapshot(quiz))


def publish(
    quiz: Quiz,
    *,
    admin_id: str,
    decision: str | None = None,
    expected_hash: str | None = None,
) -> QuizRevision:
    """`expected_hash` is what the admin saw; without it the check is skipped (services, tests)."""
    ensure_editable(quiz)
    with transaction.atomic():
        draft = _current_draft(quiz)
        if draft is None and latest_published(quiz) is not None:
            if not banks_changed(quiz):
                raise PublicationError([Problem(None, None, "no_changes")])
            draft = get_draft(quiz)
        problems = validate_for_publication(quiz)
        if problems or draft is None:
            raise PublicationError(problems)
        if expected_hash is not None and expected_hash != snapshot_hash(quiz):
            raise StalePublication(str(quiz.id))
        open_round = _open_round(quiz)
        _freeze(draft, quiz)
        keep_stateless = data_policy.has_photo_question(draft.snapshot_json)
        round_decision = None
        if open_round is not None:
            held = keep_stateless and _is_stateless(open_round)
            round_decision = Decision.STAY.value if held else _round_decision(quiz, decision)
        quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).update(
            status=QuizRevision.Status.SUPERSEDED
        )
        draft.status = QuizRevision.Status.PUBLISHED
        draft.save()
        if open_round is not None and round_decision is not None:
            _move_round(open_round, draft, round_decision)
        planned = quiz.runs.filter(status=QuizRun.Status.SCHEDULED)
        for planned_run in planned:
            if not (keep_stateless and _is_stateless(planned_run)):
                QuizRun.objects.filter(pk=planned_run.pk).update(current_revision=draft)
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="quiz.published",
            entity_type="quiz",
            entity_id=str(quiz.id),
            details={
                "revision_no": draft.revision_no,
                "checksum": draft.checksum,
                "decision": str(round_decision) if round_decision else None,
            },
        )
        events.emit("quiz.published", {"quiz_id": str(quiz.id), "revision_id": str(draft.id)})
    return draft


def publish_and_open(quiz: Quiz, *, admin_id: str, expected_hash: str | None = None) -> QuizRun:
    """Starting a quiz does both or neither, so a failed start leaves the draft a draft."""
    with transaction.atomic():
        publish(quiz, admin_id=admin_id, expected_hash=expected_hash)
        return open_run(quiz, admin_id=admin_id)


def _freeze(draft: QuizRevision, quiz: Quiz) -> None:
    questions = draft.snapshot_json["questions"]
    snapshot = {**future_snapshot(quiz), "questions": questions}
    question_types: dict[str, str] = {}
    scoring: dict[str, str] = {}

    def stamp(question: dict[str, Any]) -> ScoringStrategyPlugin:
        strategy = _scoring(question["scoring"])
        question["scoring_version"] = strategy.version
        question_types[question["type"]] = question["type_version"]
        scoring[question["scoring"]] = strategy.version
        return strategy

    max_score = Decimal(0)
    for question in questions:
        max_score += stamp(question).max_score(question["settings"])
    for row in snapshot["draws"]:
        for question in row["pool"]:
            stamp(question)
        first = row["pool"][0]  # publication was refused if a row cannot be filled
        max_score += _scoring(first["scoring"]).max_score(first["settings"]) * row["count"]
    draft.snapshot_json = snapshot
    draft.plugins_json = {"question_types": question_types, "scoring": scoring}
    draft.max_score = max_score
    draft.checksum = _canonical_hash(draft.snapshot_json)
    draft.published_at = timezone.now()


def freeze_copy(quiz: Quiz) -> QuizRevision:
    """What publication would store, for a test link. The draft stays a draft (ADR-0044)."""
    ensure_editable(quiz)
    with transaction.atomic():
        problems = validate_for_publication(quiz)
        if problems:
            raise PublicationError(problems)
        frozen = QuizRevision(
            quiz=quiz,
            revision_no=None,
            status=QuizRevision.Status.TEST_COPY,
            snapshot_json={"questions": copy.deepcopy(editable_questions(quiz))},
        )
        _freeze(frozen, quiz)
        frozen.save()
    return frozen


def _restore_quiz_fields(quiz: Quiz, snapshot: Mapping[str, Any]) -> None:
    quiz.title = snapshot["title"]
    quiz.description = snapshot.get("description", {})  # older revisions have none
    quiz.supported_locales = snapshot["locales"]
    quiz.default_locale = snapshot["default_locale"]
    quiz.save(update_fields=["title", "description", "supported_locales", "default_locale"])


def use_as_draft(quiz: Quiz, revision: QuizRevision, *, admin_id: str) -> QuizRevision:
    """The old revision stays as it is; publishing the draft gives a new number."""
    ensure_editable(quiz)
    with transaction.atomic():
        draft = get_draft(quiz)
        draft.snapshot_json = {
            "questions": copy.deepcopy(revision.snapshot_json["questions"]),
            "draws": _rows_of(revision.snapshot_json),
        }
        draft.save()
        _restore_quiz_fields(quiz, revision.snapshot_json)
        _audit_quiz("quiz.revision_restored", quiz, admin_id, {"revision_no": revision.revision_no})
    return draft


def discard_draft(quiz: Quiz, *, admin_id: str) -> None:
    ensure_editable(quiz)
    with transaction.atomic():
        draft = _current_draft(quiz)
        if draft is None:
            raise NothingToDiscard(str(quiz.id))
        published = latest_published(quiz)
        if published is None:
            raise NeverPublished(str(quiz.id))
        draft.delete()
        _restore_quiz_fields(quiz, published.snapshot_json)
        _audit_quiz("quiz.draft_discarded", quiz, admin_id, {"revision_no": draft.revision_no})


def ensure_modules_enabled(snapshot: Mapping[str, Any]) -> None:
    """A run must not start on a revision that needs a disabled module (ADR-0057)."""
    types = registry.keys("question_type")
    strategies = registry.keys("scoring_strategy")
    problems = [
        gettext("Question %(number)s needs a module that is disabled.") % {"number": number}
        for number, question in enumerate(snapshot.get("questions", []), start=1)
        if question["type"] not in types or question["scoring"] not in strategies
    ]
    if problems:
        raise RequirementUnmet(problems)


def open_run(
    quiz: Quiz,
    *,
    admin_id: str,
    deadline_at: datetime | None = None,
    limit_sec: int | None | Literal["inherit"] = "inherit",
    rules: Mapping[str, str] | None = None,
    data: Mapping[str, str] | None = None,
    results: Mapping[str, str] | None = None,
    rewards: Mapping[str, str] | None = None,
) -> QuizRun:
    ensure_editable(quiz)
    revision = latest_published(quiz)
    if revision is None:
        raise NothingPublished(str(quiz.id))
    ensure_modules_enabled(revision.snapshot_json)
    missing = requirements.unmet(quiz, requirements.of_snapshot(revision.snapshot_json, quiz))
    if missing:
        raise RequirementUnmet([item.text for item in missing])
    last = quiz.runs.aggregate(last=Max("run_no"))["last"] or 0
    chosen_rules = participants.snapshot(quiz, rules)
    chosen_data = data_policy.snapshot(quiz, data)
    data_policy.ensure_run_allowed(quiz, chosen_data, chosen_rules, revision.snapshot_json)
    chosen_results = run_results.snapshot(quiz, results)
    run_results.ensure_run_allowed(quiz, chosen_results, chosen_data[data_policy.PROFILE])
    try:
        with transaction.atomic():
            run = QuizRun.objects.create(
                quiz=quiz,
                run_no=last + 1,
                current_revision=revision,
                deadline_at=deadline_at,
                attempt_limit_sec=(
                    settings.attempt_limit_seconds(quiz) if limit_sec == "inherit" else limit_sec
                ),
                participant_rules_json=chosen_rules,
                retention_json=chosen_data,
                results_json=chosen_results,
                rewards_json=run_rewards.snapshot(quiz, rewards),
            )
            RunRevision.objects.create(
                run=run,
                revision=revision,
                active_from=run.opened_at,
                max_score=revision.max_score,
            )
            run_rewards.copy_rules(run)
            run_rewards.ensure_allowed(run)
            audit.record(
                actor_type="admin",
                actor_id=admin_id,
                action="run.opened",
                entity_type="run",
                entity_id=str(run.id),
            )
            events.emit("run.opened", {"run_id": str(run.id)})
    except IntegrityError as exc:
        raise RunAlreadyOpen(str(quiz.id)) from exc
    return run


def duplicate_quiz(quiz: Quiz, slug: str, *, admin_id: str) -> Quiz:
    """A new quiz with the same content as a draft; no revisions, rounds or attempts."""
    try:
        with transaction.atomic():
            copied = Quiz.objects.create(
                slug=slug,
                title=copy.deepcopy(quiz.title),
                description=copy.deepcopy(quiz.description),
                default_locale=quiz.default_locale,
                supported_locales=list(quiz.supported_locales),
                created_by=admin_id,
                quiz_type=quiz.quiz_type,
            )
            # Every quiz setting override goes along, the colour palette among them; the branding
            # texts, logos and custom colours (BrandingConfiguration) do not.
            AppSetting.objects.bulk_create(
                AppSetting(key=row.key, value_json=row.value_json, quiz=copied)
                for row in AppSetting.objects.filter(quiz=quiz)
            )
            QuizRevision.objects.create(
                quiz=copied,
                revision_no=1,
                snapshot_json={
                    "questions": copy.deepcopy(editable_questions(quiz)),
                    "draws": editable_draws(quiz),
                },
            )
            _audit_quiz("quiz.duplicated", copied, admin_id, {"source": str(quiz.id)})
    except IntegrityError as exc:
        raise SlugTaken(slug) from exc
    return copied


def archive_quiz(quiz: Quiz, *, admin_id: str) -> None:
    """Only the status of the published revision changes, never its content."""
    with transaction.atomic():
        if quiz.runs.filter(status__in=(QuizRun.Status.OPEN, QuizRun.Status.SCHEDULED)).exists():
            raise RunStillOpen(str(quiz.id))
        quiz.archived_at = timezone.now()
        quiz.save(update_fields=["archived_at"])
        quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).update(
            status=QuizRevision.Status.ARCHIVED
        )
        _audit_quiz("quiz.archived", quiz, admin_id)


def restore_quiz(quiz: Quiz, *, admin_id: str) -> None:
    with transaction.atomic():
        if not Quiz.objects.filter(pk=quiz.pk, archived_at__isnull=False).exists():
            return
        quiz.archived_at = None
        quiz.save(update_fields=["archived_at"])
        archived = _latest_archived(quiz)
        if archived is not None:
            quiz.revisions.filter(pk=archived.pk).update(status=QuizRevision.Status.PUBLISHED)
        _audit_quiz("quiz.restored", quiz, admin_id)


def _audit_quiz(action: str, quiz: Quiz, admin_id: str, details: dict | None = None) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="quiz",
        entity_id=str(quiz.id),
        details=details,
    )


def close_run(run: QuizRun, *, admin_id: str) -> None:
    with transaction.atomic():
        changed = QuizRun.objects.filter(pk=run.pk, status=QuizRun.Status.OPEN).update(
            status=QuizRun.Status.CLOSED, closed_at=timezone.now()
        )
        if not changed:
            return
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="run.closed",
            entity_type="run",
            entity_id=str(run.id),
        )
        events.emit("run.closed", {"run_id": str(run.id)})
