"""Matching: pairs (A to 1) and ordering.

The page never depends on the correct answer. Left and right items are sorted by independent random
ids, and a right-hand text has its own id, so neither the order nor the markup shows a pair.
"""

import json
import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from app.contracts import (
    JSON,
    AdminFormError,
    AnswerCount,
    CsvRowError,
    DefinitionRow,
    ItemGrade,
    counted,
)

MAX_ITEMS = 8
MIN_ITEMS = 2
PAIRS = "pairs"
ORDER = "order"
TOP_DOWN = "top_down"
BOTTOM_UP = "bottom_up"
POSITION = re.compile(r"[1-9][0-9]{0,2}", re.ASCII)


def _value(form: Mapping[str, Sequence[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1].strip()


def _repeated(texts: Sequence[str]) -> str | None:
    """Two texts a participant cannot tell apart. Case and extra spaces make no difference."""
    seen = set()
    for text in texts:
        key = " ".join(text.split()).casefold()
        if key and key in seen:
            return text
        seen.add(key)
    return None


def _same_text_message(text: str) -> str:
    return _("Two rows have the same text: %(text)s") % {"text": text}


def _texts(items: Sequence[Mapping], field: str, locale: str) -> list[str]:
    return [str(item.get(field, {}).get(locale, "")) for item in items]


def _is_order(config: JSON) -> bool:
    return config.get("mode") == ORDER


def _expected(config: JSON) -> list[str]:
    ids = [item["id"] for item in config["items"]]
    return ids[::-1] if config.get("direction") == BOTTOM_UP else ids


def _positions(answer: Any) -> dict[str, int]:
    """Item id to position, from the script's list or from the dropdowns without a script."""
    if not isinstance(answer, Mapping):
        return {}
    order = answer.get("order")
    if isinstance(order, list):
        return {str(item): number for number, item in enumerate(order, start=1)}
    return {
        key.removeprefix("pos_"): int(value)
        for key, value in answer.items()
        if key.startswith("pos_") and isinstance(value, str) and POSITION.fullmatch(value)
    }


class MatchingQuestion:
    id = "matching"
    version = "1.0.0"

    def label(self) -> str:
        return _("Matching")

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "mode", "items"]}

    def answer_schema(self) -> JSON:
        return {
            "type": "object",
            "properties": {"order": {"type": "array", "items": {"type": "string"}}},
            "patternProperties": {"^pair_": {"type": "string"}, "^pos_": {"type": "string"}},
        }

    def question_settings(self) -> Sequence[str]:
        return []

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["all_or_nothing", "partial"]

    def presets(self) -> Sequence[JSON]:
        return []

    def initial(self, preset: str, locales: Sequence[str]) -> JSON:
        return {}

    def validate_definition(self, config: JSON, locale: str) -> None:
        if not str(config.get("prompt", {}).get(locale, "")).strip():
            raise ValueError("the question text is missing")
        items = config.get("items", [])
        if len(items) < MIN_ITEMS:
            raise ValueError(f"at least {MIN_ITEMS} rows are needed")
        fields = ["text"] if _is_order(config) else ["text", "match"]
        for field in fields:
            texts = _texts(items, field, locale)
            if any(not text.strip() for text in texts):
                raise ValueError("a row text is missing")
            same = _repeated(texts)
            if same is not None:
                raise ValueError(_same_text_message(same))

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        if not isinstance(answer, Mapping):
            raise ValueError("an answer must be a form")
        if _is_order(config):
            self._validate_order(config, answer)
        else:
            self._validate_pairs(config, answer)

    def _validate_pairs(self, config: JSON, answer: JSON) -> None:
        items = {item["id"] for item in config["items"]}
        choices = {item["match_id"] for item in config["items"]}
        used = set()
        for key, value in answer.items():
            if not key.startswith("pair_"):
                continue
            if key.removeprefix("pair_") not in items:
                raise ValueError("unknown row")
            if value != "" and (not isinstance(value, str) or value not in choices):
                raise ValueError("unknown choice")
            if value != "" and value in used:
                raise ValueError("each choice can be used once")
            used.add(value)

    def _validate_order(self, config: JSON, answer: JSON) -> None:
        items = {item["id"] for item in config["items"]}
        if "order" in answer:
            order = answer["order"]
            if not isinstance(order, list) or any(not isinstance(item, str) for item in order):
                raise ValueError("order must be a list")
            if len(order) != len(items) or set(order) != items:
                raise ValueError("order must hold every row once")
            return
        used = set()
        for key, value in answer.items():
            if not key.startswith("pos_"):
                continue
            if key.removeprefix("pos_") not in items or not isinstance(value, str):
                raise ValueError("unknown row")
            if value == "":
                continue
            if not POSITION.fullmatch(value) or int(value) > len(items) or value in used:
                raise ValueError("each position can be used once")
            used.add(value)

    def grade(self, config: JSON, answer: JSON) -> ItemGrade:
        """No subtraction: a row is either right or not."""
        items = config["items"]
        if _is_order(config):
            positions = _positions(answer)
            right = sum(
                positions.get(item) == number
                for number, item in enumerate(_expected(config), start=1)
            )
        else:
            right = sum(answer.get(f"pair_{item['id']}") == item["match_id"] for item in items)
        return ItemGrade(right, 0, len(items))

    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        """A pair at a time, as each one earns its own part, and an order as a whole."""
        pairs: list[tuple[str, str]] = []
        items = {item["id"]: item for item in config["items"]}
        if _is_order(config):
            for answer in answers:
                placed = sorted((position, item) for item, position in _positions(answer).items())
                ids = [item for _position, item in placed if item in items]
                if ids:
                    texts = [items[item]["text"].get(locale, "") for item in ids]
                    pairs.append((",".join(ids), ", ".join(texts)))
            return counted(pairs)
        matches = {item["match_id"]: item["match"].get(locale, "") for item in config["items"]}
        for answer in answers:
            for item in config["items"]:
                chosen = answer.get(f"pair_{item['id']}") if isinstance(answer, Mapping) else None
                if isinstance(chosen, str) and chosen in matches:
                    label = f"{item['text'].get(locale, '')}: {matches[chosen]}"
                    pairs.append((f"{item['id']}:{chosen}", label))
        return counted(pairs)

    def file_fields(self, config: JSON) -> Sequence[str]:
        return []

    def needs_grading(self, config: JSON, answer: JSON | None) -> bool:
        return False

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        mode = ORDER if _value(form, "mode") == ORDER else PAIRS
        items: list[dict[str, Any]] = []
        one_sided = False
        for row in range(MAX_ITEMS):
            text = {locale: _value(form, f"item_{row}_{locale}") for locale in locales}
            match = {locale: _value(form, f"match_{row}_{locale}") for locale in locales}
            if mode == ORDER:
                match = {}
            if not any(text.values()) and not any(match.values()):
                continue
            item: dict[str, Any] = {
                "id": _value(form, f"item_{row}_id") or secrets.token_hex(4),
                "text": text,
            }
            if mode == PAIRS:
                one_sided = one_sided or not (any(text.values()) and any(match.values()))
                item["match_id"] = _value(form, f"item_{row}_match_id") or secrets.token_hex(4)
                item["match"] = match
            items.append(item)
        config: dict[str, Any] = {
            "prompt": {locale: _value(form, f"prompt_{locale}") for locale in locales},
            "mode": mode,
            "items": items,
        }
        if mode == ORDER:
            direction = _value(form, "direction")
            config["direction"] = BOTTOM_UP if direction == BOTTOM_UP else TOP_DOWN
        if one_sided:
            raise AdminFormError(_("Every pair needs both sides."), config)
        for field in ["text"] if mode == ORDER else ["text", "match"]:
            for locale in locales:
                same = _repeated(_texts(items, field, locale))
                if same is not None:
                    raise AdminFormError(_same_text_message(same), config)
        return config

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]:
        return [*(f"prompt_{locale}" for locale in locales), "config_json"]

    def from_csv(self, cells: Mapping[str, str], locales: Sequence[str]) -> JSON:
        """Builds the editor's form, so a file is refused for what the editor refuses."""
        form: dict[str, list[str]] = {
            f"prompt_{locale}": [cells.get(f"prompt_{locale}", "")] for locale in locales
        }
        if not any(value[0].strip() for value in form.values()):
            raise CsvRowError(None, _("The question has no text in any language."))
        try:
            data = json.loads(cells.get("config_json", ""))
        except ValueError as exc:
            raise CsvRowError("config_json", _("This is not valid JSON.")) from exc
        items = data.get("items") if isinstance(data, Mapping) else None
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise CsvRowError("config_json", _("Write up to 8 items in a list named items."))
        if data.get("mode") not in (PAIRS, ORDER):
            raise CsvRowError("config_json", _("The mode must be pairs or order."))
        form["mode"] = [data["mode"]]
        form["direction"] = [str(data.get("direction", TOP_DOWN))]
        for row, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise CsvRowError("config_json", _("Write up to 8 items in a list named items."))
            for field, name in (("text", "item"), ("match", "match")):
                texts = item.get(field, {})
                if not isinstance(texts, Mapping):
                    raise CsvRowError("config_json", _("Texts must be listed by language."))
                for locale in locales:
                    form[f"{name}_{row}_{locale}"] = [str(texts.get(locale, ""))]
        try:
            return self.parse_admin(form, locales)
        except AdminFormError as error:
            raise CsvRowError("config_json", str(error)) from error

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]:
        prompt = config.get("prompt") or {}
        cells = {f"prompt_{locale}": str(prompt.get(locale, "")) for locale in locales}
        data: dict[str, Any] = {
            "mode": config.get("mode", PAIRS),
            "items": [
                {
                    "text": {lo: item.get("text", {}).get(lo, "") for lo in locales},
                    **(
                        {"match": {lo: item.get("match", {}).get(lo, "") for lo in locales}}
                        if config.get("mode", PAIRS) == PAIRS
                        else {}
                    ),
                }
                for item in config.get("items", [])
            ],
        }
        if config.get("mode") == ORDER:
            data["direction"] = config.get("direction", TOP_DOWN)
        return cells | {"config_json": json.dumps(data, ensure_ascii=False)}

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        items = list(config.get("items", []))
        rows = [
            {
                "index": index,
                "id": items[index]["id"] if index < len(items) else "",
                "match_id": items[index].get("match_id", "") if index < len(items) else "",
                "text": items[index]["text"] if index < len(items) else {},
                "match": items[index].get("match", {}) if index < len(items) else {},
            }
            for index in range(MAX_ITEMS)
        ]
        return render_to_string(
            "matching/admin.html",
            {
                "prompt": config.get("prompt", {}),
                "rows": rows,
                "locales": locales,
                "mode": ORDER if _is_order(config) else PAIRS,
                "direction": config.get("direction", TOP_DOWN),
            },
        )

    def render_public(self, public_config: JSON, locale: str, answer: JSON | None = None) -> str:
        if public_config.get("mode") == ORDER:
            positions = _positions(answer)
            items = sorted(
                public_config["items"],
                key=lambda item: positions.get(item["id"], len(positions) + 1),
            )
            return render_to_string(
                "matching/public_order.html",
                {"q": public_config, "items": items, "positions": positions},
            )
        chosen = answer if isinstance(answer, Mapping) else {}
        return render_to_string(
            "matching/public_pairs.html", {"q": public_config, "chosen": chosen}
        )

    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str:
        items = {item["id"]: item for item in config["items"]}
        if _is_order(config):
            positions = _positions(answer)
            rows = [
                {"text": items[item]["text"].get(locale, ""), "position": positions.get(item)}
                for item in _expected(config)
            ]
            return render_to_string("matching/solution.html", {"order": True, "rows": rows})
        chosen = answer if isinstance(answer, Mapping) else {}
        by_match = {item["match_id"]: item["match"].get(locale, "") for item in config["items"]}
        rows = []
        for item in config["items"]:
            theirs = chosen.get(f"pair_{item['id']}")
            wrong = isinstance(theirs, str) and theirs in by_match and theirs != item["match_id"]
            rows.append(
                {
                    "text": item["text"].get(locale, ""),
                    "match": item["match"].get(locale, ""),
                    "theirs": by_match[theirs] if wrong else None,
                }
            )
        return render_to_string("matching/solution.html", {"order": False, "rows": rows})

    def describe_definition(self, config: JSON, locales: Sequence[str]) -> list[DefinitionRow]:
        prompt = config.get("prompt", {})
        items = config.get("items", [])
        main = locales[0]
        rows = [DefinitionRow("prompt", _("Question"), lo, prompt.get(lo, "")) for lo in locales]
        for item in items:
            rows += [
                DefinitionRow(f"item:{item['id']}", _("Row"), lo, item["text"].get(lo, ""))
                for lo in locales
            ]
            if not _is_order(config):
                rows += [
                    DefinitionRow(
                        f"match:{item['id']}", _("Matches"), lo, item.get("match", {}).get(lo, "")
                    )
                    for lo in locales
                ]
        numbered = [f"{n}: {i['text'].get(main, '')}" for n, i in enumerate(items, start=1)]
        rows.append(DefinitionRow("order", _("Order of rows"), None, ", ".join(numbered)))
        mode = _("Ordering") if _is_order(config) else _("Pairs")
        rows.append(DefinitionRow("mode", _("Kind"), None, mode))
        if _is_order(config):
            down = config.get("direction") != BOTTOM_UP
            direction = _("From top to bottom") if down else _("From bottom to top")
            rows.append(DefinitionRow("direction", _("Direction"), None, direction))
        return rows

    def public_payload(self, config: JSON, locale: str, quiz_settings: JSON | None = None) -> JSON:
        items = config["items"]
        left = sorted(items, key=lambda item: item["id"])
        payload: dict[str, Any] = {
            "prompt": config["prompt"].get(locale, ""),
            "mode": ORDER if _is_order(config) else PAIRS,
            "items": [{"id": item["id"], "text": item["text"].get(locale, "")} for item in left],
        }
        if _is_order(config):
            payload["direction"] = config.get("direction", TOP_DOWN)
        else:
            right = sorted(items, key=lambda item: item["match_id"])
            payload["choices"] = [
                {"id": item["match_id"], "text": item["match"].get(locale, "")} for item in right
            ]
        return payload
