"""Playing a draft or revision with nothing stored (FR-13). The attempt is never saved.

What the next request needs travels in a signed token. The admin holds it, and only an admin
reaches these views, but the signature keeps a token from being edited into another quiz.
"""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

from django.core import signing

from app.contracts import JSON, QuestionTypePlugin, ScoringStrategyPlugin
from app.domain import attempts, authoring, selection, settings
from app.domain.models import Attempt, Quiz, QuizRevision, QuizRun
from app.kernel import registry

SALT = "kvizotron.preview"
MAX_AGE = timedelta(hours=24)


class PreviewStale(Exception):
    """The draft changed under an open page, or the token is not valid for this quiz."""


@dataclass(frozen=True)
class Started:
    attempt: Attempt
    token: str
    problems: list[authoring.Problem]


def _attempt(
    quiz: Quiz, snapshot: JSON, selection_json: dict[str, Any], flow: dict[str, Any]
) -> Attempt:
    return Attempt(
        run=QuizRun(quiz=quiz),
        revision=QuizRevision(quiz=quiz, snapshot_json=snapshot),
        selection_json=selection_json,
        settings_json=flow,
    )


def _snapshot(quiz: Quiz, revision: QuizRevision | None) -> JSON:
    return revision.snapshot_json if revision is not None else authoring.future_snapshot(quiz)


def start(quiz: Quiz, revision: QuizRevision | None) -> Started:
    """`revision=None` means the draft. Raises `selection.CannotDraw`, listed in `problems` too."""
    snapshot = _snapshot(quiz, revision)
    problems = authoring.validate_for_publication(quiz) if revision is None else []
    flow = settings.flow(quiz)
    selected = {
        "items": selection.choose(snapshot, flow.shuffle_questions),
        "seed": secrets.token_urlsafe(8) if flow.shuffle_options else None,
        "question_seed": secrets.token_urlsafe(8),
    }
    behaviour = {
        "navigation": flow.navigation,
        "moment": flow.moment,
        "level": flow.level,
        "shuffle_questions": flow.shuffle_questions,
    }
    token = signing.dumps(
        {
            "quiz": str(quiz.pk),
            "revision_no": revision.revision_no if revision is not None else None,
            "hash": authoring.snapshot_hash(quiz) if revision is None else None,
            "selection": selected,
            "flow": behaviour,
        },
        salt=SALT,
    )
    return Started(_attempt(quiz, snapshot, selected, behaviour), token, problems)


def load(token: str, quiz: Quiz) -> Attempt:
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as exc:
        raise PreviewStale from exc
    if data["quiz"] != str(quiz.pk):
        raise PreviewStale
    revision = None
    if data["revision_no"] is not None:
        revision = quiz.revisions.filter(revision_no=data["revision_no"]).first()
        if revision is None:
            raise PreviewStale
    elif data["hash"] != authoring.snapshot_hash(quiz):
        raise PreviewStale
    return _attempt(quiz, _snapshot(quiz, revision), data["selection"], data["flow"])


def unusable(attempt: Attempt, locale: str) -> dict[str, str]:
    """Questions that cannot be shown in this language yet: a draft may be incomplete."""
    found = {}
    for question in attempts.questions_of(attempt):
        try:
            plugin = cast(QuestionTypePlugin, registry.get("question_type", question["type"]))
            registry.get("scoring_strategy", question["scoring"])
            plugin.validate_definition(question["definition"], locale)
        except (ValueError, registry.UnknownPort) as exc:
            found[question["id"]] = str(exc)
    return found


def keep_usable(attempt: Attempt, locale: str) -> None:
    """What the page showed as a notice takes no part in the score or the reveal."""
    bad = unusable(attempt, locale)
    selected = dict(attempt.selection_json or {})
    selected["items"] = [item for item in attempts.items_of(attempt) if item["id"] not in bad]
    attempt.selection_json = selected


def score(attempt: Attempt, answers: Mapping[str, JSON]) -> attempts.AttemptResult:
    """Raises `AttemptError("invalid_answer")`, like a real submission."""
    earned = Decimal(0)
    maximum = Decimal(0)
    correct = 0
    pending = False
    for question in attempts.questions_of(attempt):
        strategy = cast(
            ScoringStrategyPlugin, registry.get("scoring_strategy", question["scoring"])
        )
        maximum += strategy.max_score(question["settings"])
        answer = answers.get(question["id"])
        if answer is None:
            continue
        breakdown = attempts.evaluate(question, answer)
        earned += breakdown.earned_points
        correct += breakdown.correct_count or 0
        pending = pending or (
            attempts.needs_grading(question, answer)
            and breakdown.earned_points < breakdown.max_points
        )
    return attempts.AttemptResult(earned, maximum, correct, pending)
