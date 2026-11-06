"""Single correct answer (FR-15). The option ids say nothing about which option is correct."""

import secrets
from collections.abc import Mapping, Sequence

from django.template.loader import render_to_string

from app.contracts import JSON, AdminFormError

MAX_OPTIONS = 6
MIN_OPTIONS = 2


def _value(form: Mapping[str, Sequence[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1].strip()


class ChoiceSingleQuestion:
    id = "choice.single"
    version = "1.0.0"

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "options", "correct"]}

    def answer_schema(self) -> JSON:
        return {
            "type": "object",
            "required": ["option"],
            "properties": {"option": {"type": "string"}},
        }

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["all_or_nothing"]

    def validate_definition(self, config: JSON, locale: str) -> None:
        if not str(config.get("prompt", {}).get(locale, "")).strip():
            raise ValueError("the question text is missing")
        options = config.get("options", [])
        if len(options) < MIN_OPTIONS:
            raise ValueError(f"at least {MIN_OPTIONS} options are needed")
        if any(not str(o["text"].get(locale, "")).strip() for o in options):
            raise ValueError("an option text is missing")
        if config.get("correct") not in {o["id"] for o in options}:
            raise ValueError("the correct option is not chosen")

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        option = answer.get("option") if isinstance(answer, Mapping) else None
        if not isinstance(option, str) or option not in {o["id"] for o in config["options"]}:
            raise ValueError("unknown option")

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        options = []
        correct = None
        chosen = _value(form, "correct")
        for row in range(MAX_OPTIONS):
            text = {locale: _value(form, f"option_{row}_{locale}") for locale in locales}
            if not any(text.values()):
                continue
            option_id = _value(form, f"option_{row}_id") or secrets.token_hex(4)
            options.append({"id": option_id, "text": text})
            if chosen == str(row):
                correct = option_id
        config = {
            "prompt": {locale: _value(form, f"prompt_{locale}") for locale in locales},
            "options": options,
            "correct": correct,
        }
        if correct is None:
            raise AdminFormError("Choose the correct option among the filled rows", config)
        return config

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        options = list(config.get("options", []))
        rows = [
            {
                "index": index,
                "id": options[index]["id"] if index < len(options) else "",
                "text": options[index]["text"] if index < len(options) else {},
                "correct": index < len(options) and options[index]["id"] == config.get("correct"),
            }
            for index in range(MAX_OPTIONS)
        ]
        return render_to_string(
            "choice_single/admin.html",
            {"prompt": config.get("prompt", {}), "rows": rows, "locales": locales},
        )

    def render_public(self, public_config: JSON, locale: str) -> str:
        return render_to_string("choice_single/public.html", {"q": public_config})

    def public_payload(self, config: JSON, locale: str) -> JSON:
        return {
            "prompt": config["prompt"].get(locale, ""),
            "options": [
                {"id": option["id"], "text": option["text"].get(locale, "")}
                for option in config["options"]
            ],
        }
