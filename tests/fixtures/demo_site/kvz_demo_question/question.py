from decimal import Decimal

from django.template.loader import render_to_string
from django.utils.html import escape

from app.contracts import CsvRowError, DefinitionRow, ItemGrade, ScoreBreakdown


class DemoNumberQuestion:
    id = "demo.number"

    def label(self):
        return "Demo number"

    version = "1.0.0"

    def config_schema(self):
        return {"type": "object", "required": ["prompt", "answer"]}

    def answer_schema(self):
        return {"type": "object", "required": ["value"]}

    def question_settings(self):
        return []

    def summarize(self, config, answers, locale):
        return []

    def file_fields(self, config):
        return []

    def needs_grading(self, config, answer):
        return False

    def available_scoring_strategies(self):
        return ["demo.exact"]

    def validate_definition(self, config, locale):
        if not isinstance(config.get("answer"), int):
            raise ValueError("answer must be an integer")

    def validate_submission(self, config, answer):
        value = answer.get("value") if isinstance(answer, dict) else None
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("value must be an integer")

    def parse_admin(self, form, locales):
        try:
            return {"prompt": form["prompt"][-1], "answer": int(form["answer"][-1])}
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError("prompt and integer answer are required") from exc

    def csv_columns(self, locales):
        return ["prompt", "answer"]

    def from_csv(self, cells, locales):
        try:
            return {"prompt": cells["prompt"], "answer": int(cells["answer"])}
        except (KeyError, ValueError) as exc:
            raise CsvRowError("answer", "prompt and integer answer are required") from exc

    def to_csv(self, config, locales):
        return {"prompt": config["prompt"], "answer": str(config["answer"])}

    def render_admin(self, config, locales):
        prompt = escape(config.get("prompt", ""))
        answer = escape(config.get("answer", ""))
        return (
            f'<label>Prompt <input name="prompt" value="{prompt}"></label>'
            f'<label>Answer <input name="answer" value="{answer}"></label>'
        )

    def render_public(self, public_config, locale, answer=None):
        context = {"q": public_config, "answer": answer}
        return render_to_string("kvz_demo_question/play.html", context)

    def render_solution(self, config, locale, answer):
        return render_to_string("kvz_demo_question/solution.html", {"config": config})

    def describe_definition(self, config, locales):
        return [
            DefinitionRow("prompt", "Prompt", None, str(config.get("prompt", ""))),
            DefinitionRow("answer", "Answer", None, str(config.get("answer", ""))),
        ]

    def public_payload(self, config, locale, quiz_settings=None):
        return {"prompt": config["prompt"]}

    def presets(self):
        return []

    def initial(self, preset, locales):
        return {}

    def grade(self, config, answer):
        is_right = int(answer["value"]) == config["answer"]
        return ItemGrade(int(is_right), int(not is_right), 1)


class DemoExactScoring:
    id = "demo.exact"
    version = "1.0.0"

    def label(self):
        return "Demo exact"

    def supports(self, question_type_id):
        return question_type_id == "demo.number"

    def max_score(self, settings):
        return Decimal(1)

    def evaluate(self, grade, settings):
        correct = grade.right == grade.total
        return ScoreBreakdown(Decimal(int(correct)), Decimal(1), int(correct), {})
