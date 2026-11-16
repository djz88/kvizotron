"""The pass mark as a participant reads it on a result page (test add-ons).

The domain judges (`results.judge`, `kept_passed`); this module only words the verdict, so the
templates hold no rule. An attempt line says how this attempt stands; a kept line is added when
the participant has several submitted attempts.
"""

from decimal import ROUND_FLOOR, Decimal
from typing import Any

from django.utils import translation
from django.utils.translation import gettext

from app.api.jinja import number
from app.domain import results
from app.domain.models import Attempt, Quiz, QuizRun

_HUNDRED = Decimal(100)
_TENTH = Decimal("0.1")


def _percent(score: Decimal, maximum: Decimal) -> str:
    return number((score / maximum * _HUNDRED).quantize(_TENTH, ROUND_FLOOR))


def _kept_sentence(rule: str) -> str:
    """Whole sentences per rule, so cs and uk can decline the words as they need."""
    sentences = {
        "best": gettext("Kept score: %(percent)s %% (best of %(count)s) — %(verdict)s"),
        "first": gettext("Kept score: %(percent)s %% (first of %(count)s) — %(verdict)s"),
        "last": gettext("Kept score: %(percent)s %% (last of %(count)s) — %(verdict)s"),
        "average": gettext("Kept score: %(percent)s %% (average of %(count)s) — %(verdict)s"),
    }
    return sentences[rule]


def line(
    score: Decimal, maximum: Decimal, pending: bool, mark: Decimal | None, locale: str
) -> str | None:
    """How one attempt stands against the mark; nothing without a mark or a maximum."""
    if mark is None or maximum <= 0:
        return None
    with translation.override(locale):
        if pending:
            return gettext("Waiting for grading")
        values = {"percent": _percent(score, maximum), "mark": number(mark)}
        if results.judge(score, maximum, mark):
            return gettext("Passed ✓ — %(percent)s %% (pass mark %(mark)s %%)") % values
        return gettext("Not passed — %(percent)s %% (pass mark %(mark)s %%)") % values


def _kept_line(attempt: Attempt, run: QuizRun, locale: str) -> str | None:
    if attempt.participant_id is None or attempt.pk is None:
        return None
    found = results.kept(attempt.participant)  # type: ignore[arg-type]
    if found is None or found.count < 2 or found.figures.max_score <= 0:
        return None
    passed = results.kept_passed(found, run)
    with translation.override(locale):
        if found.waiting:
            verdict = gettext("Waiting for grading")
        elif passed is None:
            return None
        elif passed:
            verdict = gettext("Passed ✓")
        else:
            verdict = gettext("Not passed")
        return _kept_sentence(found.rule) % {
            "percent": _percent(found.figures.score, found.figures.max_score),
            "count": found.count,
            "verdict": verdict,
        }


def context(
    attempt: Attempt,
    locale: str,
    *,
    score: Decimal,
    maximum: Decimal,
    pending: bool,
) -> dict[str, Any]:
    """`pass_attempt` and `pass_kept` for a result page; empty when the run has no pass mark."""
    run = attempt.run
    mark = results.pass_mark(run)
    own = line(score, maximum, pending, mark, locale)
    if own is None:
        return {}
    return {"pass_attempt": own, "pass_kept": _kept_line(attempt, run, locale)}


def preview_context(
    quiz: Quiz, locale: str, *, score: Decimal, maximum: Decimal, pending: bool
) -> dict[str, Any]:
    """The same line for the preview, which keeps no attempt: the quiz's mark as it is now."""
    mark = Decimal(results.rules_for_quiz(quiz)[results.PASS_MARK])
    own = line(score, maximum, pending, mark if mark > 0 else None, locale)
    return {} if own is None else {"pass_attempt": own, "pass_kept": None}
