"""Basic scoring (FR-24). Pure: the result depends only on the definition, answer and settings."""

from app.contracts import JSON, ScoreBreakdown

DEFAULT_POINTS = 1


class AllOrNothing:
    id = "all_or_nothing"
    version = "1.0.0"

    def supports(self, question_type_id: str) -> bool:
        return question_type_id == "choice.single"

    def max_score(self, definition: JSON, settings: JSON) -> float:
        return float(settings.get("points", DEFAULT_POINTS))

    def evaluate(self, definition: JSON, answer: JSON, settings: JSON) -> ScoreBreakdown:
        points = self.max_score(definition, settings)
        correct = answer.get("option") == definition["correct"]
        return ScoreBreakdown(points if correct else 0.0, points, int(correct), {})
