"""Editing a draft, publishing it as an immutable revision, opening and closing runs."""

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from app.contracts import JSON, QuestionTypePlugin, ScoringStrategyPlugin
from app.domain.models import Quiz, QuizRevision, QuizRun
from app.kernel import audit, events, registry

DEFAULT_POINTS = 1


class AuthoringError(Exception):
    pass


class QuestionNotFound(AuthoringError):
    pass


class UnknownQuestionType(AuthoringError):
    pass


class NothingPublished(AuthoringError):
    pass


class RunAlreadyOpen(AuthoringError):
    pass


@dataclass(frozen=True)
class Problem:
    question_no: int | None
    locale: str | None
    code: str  # no_questions, no_changes, title_missing, type_unavailable, invalid
    detail: str = ""


class PublicationError(AuthoringError):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} problems block publication")
        self.problems = problems


def _question_type(type_id: str) -> QuestionTypePlugin:
    return cast(QuestionTypePlugin, registry.get("question_type", type_id))


def _scoring(strategy_id: str, **kwargs: Any) -> ScoringStrategyPlugin:
    return cast(ScoringStrategyPlugin, registry.get("scoring_strategy", strategy_id, **kwargs))


def _latest_published(quiz: Quiz) -> QuizRevision | None:
    return quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).first()


def _current_draft(quiz: Quiz) -> QuizRevision | None:
    return quiz.revisions.filter(status=QuizRevision.Status.DRAFT).first()


def get_draft(quiz: Quiz) -> QuizRevision:
    """The quiz's draft; created from the latest published revision when there is none."""
    draft = _current_draft(quiz)
    if draft is not None:
        return draft
    published = _latest_published(quiz)
    questions = published.snapshot_json["questions"] if published else []
    last = quiz.revisions.aggregate(last=Max("revision_no"))["last"] or 0
    try:
        with transaction.atomic():
            return QuizRevision.objects.create(
                quiz=quiz, revision_no=last + 1, snapshot_json={"questions": questions}
            )
    except IntegrityError:  # another admin started the draft at the same moment
        draft = _current_draft(quiz)
        if draft is None:
            raise
        return draft


def editable_questions(quiz: Quiz) -> list[dict[str, Any]]:
    revision = _current_draft(quiz) or _latest_published(quiz)
    return list(revision.snapshot_json["questions"]) if revision else []


def save_question(quiz: Quiz, question_id: str | None, type_id: str, config: JSON) -> str:
    """Store a question in the draft. It may be incomplete; publication validates it."""
    try:
        plugin = _question_type(type_id)
    except LookupError as exc:
        raise UnknownQuestionType(type_id) from exc
    with transaction.atomic():
        draft = get_draft(quiz)
        questions = draft.snapshot_json["questions"]
        if question_id is None:
            scoring_id = plugin.available_scoring_strategies()[0]
            question: dict[str, Any] = {
                "id": str(uuid.uuid7()),
                "scoring": scoring_id,
                "settings": {"points": DEFAULT_POINTS},
            }
            questions.append(question)
        else:
            question = _find(questions, question_id)
        question.update(type=type_id, type_version=plugin.version, definition=dict(config))
        draft.save()
    return question["id"]


def delete_question(quiz: Quiz, question_id: str) -> None:
    with transaction.atomic():
        draft = get_draft(quiz)
        questions = draft.snapshot_json["questions"]
        questions.remove(_find(questions, question_id))
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
    if not questions:
        problems.append(Problem(None, None, "no_questions"))
    for number, question in enumerate(questions, start=1):
        problems += _question_problems(number, question, quiz.supported_locales)
    return problems


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
    return problems


def publish(quiz: Quiz, *, admin_id: str) -> QuizRevision:
    with transaction.atomic():
        draft = _current_draft(quiz)
        if draft is None and _latest_published(quiz) is not None:
            raise PublicationError([Problem(None, None, "no_changes")])
        problems = validate_for_publication(quiz)
        if problems or draft is None:
            raise PublicationError(problems)
        _freeze(draft, quiz)
        quiz.revisions.filter(status=QuizRevision.Status.PUBLISHED).update(
            status=QuizRevision.Status.SUPERSEDED
        )
        draft.status = QuizRevision.Status.PUBLISHED
        draft.save()
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="quiz.published",
            entity_type="quiz",
            entity_id=str(quiz.id),
            details={"revision_no": draft.revision_no, "checksum": draft.checksum},
        )
        events.emit("quiz.published", {"quiz_id": str(quiz.id), "revision_id": str(draft.id)})
    return draft


def _freeze(draft: QuizRevision, quiz: Quiz) -> None:
    questions = draft.snapshot_json["questions"]
    question_types: dict[str, str] = {}
    scoring: dict[str, str] = {}
    max_score = Decimal(0)
    for question in questions:
        strategy = _scoring(question["scoring"])
        question["scoring_version"] = strategy.version
        question_types[question["type"]] = question["type_version"]
        scoring[question["scoring"]] = strategy.version
        max_score += Decimal(str(strategy.max_score(question["definition"], question["settings"])))
    draft.snapshot_json = {
        "title": quiz.title,
        "default_locale": quiz.default_locale,
        "locales": quiz.supported_locales,
        "questions": questions,
    }
    draft.plugins_json = {"question_types": question_types, "scoring": scoring}
    draft.max_score = max_score
    canonical = json.dumps(draft.snapshot_json, sort_keys=True, separators=(",", ":"))
    draft.checksum = hashlib.sha256(canonical.encode()).hexdigest()
    draft.published_at = timezone.now()


def open_run(quiz: Quiz, *, admin_id: str) -> QuizRun:
    revision = _latest_published(quiz)
    if revision is None:
        raise NothingPublished(str(quiz.id))
    last = quiz.runs.aggregate(last=Max("run_no"))["last"] or 0
    try:
        with transaction.atomic():
            run = QuizRun.objects.create(quiz=quiz, run_no=last + 1, current_revision=revision)
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
