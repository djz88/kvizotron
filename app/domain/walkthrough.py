"""What everyone may see of a finished run (ADR-0046, AC-60). Attempts are not named here."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from django.db import transaction

from app.contracts import PHOTO_PUBLIC, AnswerCount, QuestionTypePlugin
from app.domain import settings, visibility
from app.domain.models import Attempt, AttemptAnswer, HiddenAnswerValue, QuizRun
from app.kernel import audit, registry


@dataclass(frozen=True)
class ShownCount:
    count: AnswerCount
    hidden: bool


@dataclass
class WalkthroughQuestion:
    question: Mapping[str, Any]
    counts: list[ShownCount] = field(default_factory=list)
    photos: list[AttemptAnswer] = field(default_factory=list)


def value_key(key: str) -> str:
    """Free text can say anything, so a stored or audited key never repeats it."""
    return hashlib.sha256(key.encode()).hexdigest()


def _answered_rows(run: QuizRun) -> list[AttemptAnswer]:
    return list(
        AttemptAnswer.objects.filter(
            attempt__run=run, attempt__status__in=Attempt.FINISHED
        ).select_related("attempt__run")
    )


def _questions(run: QuizRun, rows: list[AttemptAnswer]) -> list[Mapping[str, Any]]:
    """Of its last revision. A question from a draw counts once somebody got it."""
    snapshot = run.current_revision.snapshot_json
    found = list(snapshot.get("questions", []))
    answered = {row.question_id for row in rows}
    seen = {question["id"] for question in found}
    for draw in snapshot.get("draws", []):
        for question in draw.get("pool", []):
            if question["id"] in answered and question["id"] not in seen:
                seen.add(question["id"])
                found.append(question)
    return found


def shows_answers(run: QuizRun) -> bool:
    return settings.answers_visibility(run.quiz) == settings.AnswersVisibility.PUBLIC


def available(run: QuizRun) -> bool:
    if (
        run.status != QuizRun.Status.CLOSED
        or run.kind != QuizRun.Kind.NORMAL
        or run.quiz.archived_at is not None
    ):
        return False
    return shows_answers(run) or any(
        visibility.photo_level(run.quiz, question) == PHOTO_PUBLIC
        and _plugin(question).file_fields(question["definition"])
        for question in _questions(run, _answered_rows(run))
    )


def _plugin(question: Mapping[str, Any]) -> QuestionTypePlugin:
    return cast(
        QuestionTypePlugin, registry.get("question_type", question["type"], include_disabled=True)
    )


def of_run(run: QuizRun, locale: str) -> list[WalkthroughQuestion]:
    """Hidden values are marked, for the admin's page to offer them back; `public_counts` drops."""
    rows = _answered_rows(run)
    answers = shows_answers(run)
    hidden = {
        (question, key)
        for question, key in HiddenAnswerValue.objects.filter(run=run).values_list(
            "question_id", "value_key"
        )
    }
    found = []
    for question in _questions(run, rows):
        plugin = _plugin(question)
        is_photo = bool(plugin.file_fields(question["definition"]))
        public_photos = is_photo and visibility.photo_level(run.quiz, question) == PHOTO_PUBLIC
        if not answers and not public_photos:
            continue
        own = [row for row in rows if row.question_id == question["id"]]
        shown = WalkthroughQuestion(question)
        if answers:
            given = [row.answer_json for row in own if not row.removed]
            shown.counts = [
                ShownCount(count, (question["id"], value_key(count.key)) in hidden)
                for count in plugin.summarize(question["definition"], given, locale)
            ]
        if public_photos:
            shown.photos = [
                row for row in own if visibility.public_sees_photo(row, run.quiz, question)
            ]
        found.append(shown)
    return found


def photo_for_public(run: QuizRun, answer_id: Any) -> AttemptAnswer | None:
    """The row, if everyone may see its photo. Checked anew for every request."""
    if not available(run):
        return None
    row = (
        AttemptAnswer.objects.filter(
            pk=answer_id, attempt__run=run, attempt__status__in=Attempt.FINISHED
        )
        .select_related("attempt__run")
        .first()
    )
    if row is None:
        return None
    question = next(
        (item for item in _questions(run, [row]) if item["id"] == row.question_id), None
    )
    if question is None or not visibility.public_sees_photo(row, run.quiz, question):
        return None
    return row


def hide_value(run: QuizRun, question_id: str, key: str, *, admin_id: str) -> None:
    with transaction.atomic():
        HiddenAnswerValue.objects.get_or_create(
            run=run,
            question_id=question_id,
            value_key=value_key(key),
            defaults={"hidden_by": admin_id},
        )
        _audit("answer.value_hidden", run, question_id, key, admin_id)


def show_value(run: QuizRun, question_id: str, key: str, *, admin_id: str) -> None:
    with transaction.atomic():
        HiddenAnswerValue.objects.filter(
            run=run, question_id=question_id, value_key=value_key(key)
        ).delete()
        _audit("answer.value_shown", run, question_id, key, admin_id)


def _audit(action: str, run: QuizRun, question_id: str, key: str, admin_id: str) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="run",
        entity_id=str(run.id),
        details={"question_id": question_id, "value": value_key(key)},
    )
