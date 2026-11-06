from django.template.loader import render_to_string
from django.utils.html import escape

from app.contracts import ScoreBreakdown


class DemoNumberQuestion:
    id = "demo.number"
    version = "1.0.0"

    def config_schema(self):
        return {"type": "object", "required": ["prompt", "answer"]}

    def answer_schema(self):
        return {"type": "object", "required": ["value"]}

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

    def render_admin(self, config, locales):
        prompt = escape(config.get("prompt", ""))
        answer = escape(config.get("answer", ""))
        return (
            f'<label>Prompt <input name="prompt" value="{prompt}"></label>'
            f'<label>Answer <input name="answer" value="{answer}"></label>'
        )

    def render_public(self, public_config, locale):
        return render_to_string("kvz_demo_question/play.html", {"q": public_config})

    def public_payload(self, config, locale):
        return {"prompt": config["prompt"]}


class DemoExactScoring:
    id = "demo.exact"
    version = "1.0.0"

    def supports(self, question_type_id):
        return question_type_id == "demo.number"

    def max_score(self, definition, settings):
        return 1.0

    def evaluate(self, definition, answer, settings):
        correct = int(answer["value"]) == definition["answer"]
        return ScoreBreakdown(1.0 if correct else 0.0, 1.0, int(correct), {})
