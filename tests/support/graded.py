"""A question type a person finishes grading, before any real one is involved."""

from app.contracts import ItemGrade
from app.domain import authoring
from app.plugins.questions.number.plugin import NumberQuestion

TYPE_ID = "graded"


class GradedQuestion(NumberQuestion):
    """Pays 2 of 10 once something is handed in under `image`."""

    id = TYPE_ID

    def available_scoring_strategies(self):
        return ["partial"]

    def file_fields(self, config):
        return ["image"]

    def needs_grading(self, config, answer):
        return bool(answer and answer.get("image"))

    def validate_definition(self, config, locale):
        pass

    def validate_submission(self, config, answer):
        if not isinstance(answer, dict):
            raise ValueError("an answer must be a form")

    def grade(self, config, answer):
        share = config.get("share", (2, 10))
        return ItemGrade(share[0] if answer.get("image") else 0, 0, share[1])


def add_graded(quiz, points=10, **definition):
    config = {"prompt": {locale: "Fotka" for locale in quiz.supported_locales}, **definition}
    return authoring.save_question(quiz, None, TYPE_ID, config, points=points, scoring="partial")
