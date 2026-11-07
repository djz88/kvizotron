"""Basic scoring (FR-24). A strategy only weighs a grade; the question type made it."""

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from django.utils.translation import gettext as _

from app.contracts import JSON, ItemGrade, ScoreBreakdown

DEFAULT_POINTS = 1
PLACES = Decimal("0.0001")


def _points(settings: JSON) -> int:
    return int(settings.get("points", DEFAULT_POINTS))


def _is_complete(grade: ItemGrade) -> bool:
    return grade.total > 0 and grade.right == grade.total and grade.wrong == 0


class AllOrNothing:
    id = "all_or_nothing"
    version = "1.0.0"

    def label(self) -> str:
        return _("All or nothing")

    def supports(self, question_type_id: str) -> bool:
        return True

    def max_score(self, settings: JSON) -> Decimal:
        return Decimal(_points(settings))

    def evaluate(self, grade: ItemGrade, settings: JSON) -> ScoreBreakdown:
        points = self.max_score(settings)
        complete = _is_complete(grade)
        return ScoreBreakdown(points if complete else Decimal(0), points, int(complete), {})


class Partial:
    """Pays for right minus wrong. Computed once, so three thirds make exactly the points."""

    id = "partial"
    version = "1.0.0"

    def label(self) -> str:
        return _("Part by part")

    def supports(self, question_type_id: str) -> bool:
        return True

    def max_score(self, settings: JSON) -> Decimal:
        return Decimal(_points(settings))

    def evaluate(self, grade: ItemGrade, settings: JSON) -> ScoreBreakdown:
        points = self.max_score(settings)
        earned = Fraction(0)
        if grade.total > 0:
            earned = _points(settings) * Fraction(max(0, grade.right - grade.wrong), grade.total)
        return ScoreBreakdown(_to_decimal(earned), points, int(_is_complete(grade)), {})


def _to_decimal(value: Fraction) -> Decimal:
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(PLACES, rounding=ROUND_HALF_UP)
