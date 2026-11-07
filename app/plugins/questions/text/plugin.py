"""A written answer: one field under the question, or numbered blanks inside its sentence.

Word order differs between languages, so `{1}` and `{2}` may stand in any order, and an answer is
right if it matches an accepted one in any language. The page never holds an accepted answer.
"""

import re
import secrets
import unicodedata
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
from app.contracts.question_image import (
    ImageLabels,
    csv_image_cells,
    csv_image_form,
    form_value,
    has_alt,
    image_rows,
    public_image,
    read_image,
)

MAX_BLANKS = 10
MAX_ANSWER = 500
TOKEN = re.compile(r"\{\{|\{(\d{1,3})\}", re.ASCII)
SWITCHES = ("ignore_case", "ignore_spaces", "ignore_diacritics")
DEFAULTS = {"ignore_case": True, "ignore_spaces": True, "ignore_diacritics": False}


def _without_latin_marks(text: str) -> str:
    """Decided by the letter, so `й` and `ї` stay, as there they make a different letter."""
    kept: list[str] = []
    latin = False
    for char in unicodedata.normalize("NFD", text):
        if unicodedata.combining(char):
            if not latin:
                kept.append(char)
            continue
        latin = unicodedata.name(char, "").startswith("LATIN")
        kept.append(char)
    return "".join(kept)


def normalized(
    text: str, *, ignore_case: bool, ignore_spaces: bool, ignore_diacritics: bool
) -> str:
    value = unicodedata.normalize("NFC", text)
    if ignore_spaces:
        value = " ".join(value.split())
    if ignore_diacritics:
        value = _without_latin_marks(value)
    if ignore_case:
        value = value.casefold()
    return unicodedata.normalize("NFC", value)


def comparison(config: JSON) -> dict[str, bool]:
    return {switch: bool(config.get(switch, DEFAULTS[switch])) for switch in SWITCHES}


def _markers(prompt: str) -> set[int]:
    return {int(match[1]) for match in TOKEN.finditer(prompt) if match[1]}


def _repeats_a_marker(prompt: str) -> bool:
    """Two inputs of one name would keep only the last, so an answer would vanish unseen."""
    numbers = [int(match[1]) for match in TOKEN.finditer(prompt) if match[1]]
    return len(numbers) != len(set(numbers))


def _repeat_message() -> str:
    return _("Each blank can stand only once in the question's text.")


def _all_markers(config: JSON) -> set[int]:
    prompts = (config.get("prompt") or {}).values()
    return {number for prompt in prompts for number in _markers(str(prompt))}


def _segments(prompt: str) -> list[dict[str, Any]]:
    """Text and blanks in the order of this language. The template escapes each piece."""
    parts: list[dict[str, Any]] = []
    text = ""
    position = 0
    for match in TOKEN.finditer(prompt):
        text += prompt[position : match.start()]
        position = match.end()
        if match[1]:
            parts.append({"text": text})
            parts.append({"blank": int(match[1])})
            text = ""
        else:
            text += "{"
    parts.append({"text": text + prompt[position:]})
    return [part for part in parts if part.get("text") != ""]


def _literal(prompt: str) -> str:
    """The sentence as plain text, for wherever it is only named."""
    return TOKEN.sub(lambda match: "___" if match[1] else "{", prompt)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _labels() -> ImageLabels:
    return ImageLabels(_("Image"), _("No copy"), _("Image address"), _("Image description"))


def _markers_message(numbers: set[int]) -> str | None:
    if len(numbers) > MAX_BLANKS or (numbers and max(numbers) > MAX_BLANKS):
        return _("A question can have at most %(count)s blanks.") % {"count": MAX_BLANKS}
    if numbers and numbers != set(range(1, max(numbers) + 1)):
        return _("Number the blanks in order from {1}, without a gap.")
    return None


def _value_of(answer: Any, number: int) -> str:
    value = answer.get(f"blank_{number}", "") if isinstance(answer, Mapping) else ""
    return value if isinstance(value, str) else ""


class TextQuestion:
    id = "text"
    version = "1.0.0"

    def label(self) -> str:
        return _("Text")

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "blanks"]}

    def answer_schema(self) -> JSON:
        return {"type": "object", "patternProperties": {"^blank_[0-9]+$": {"type": "string"}}}

    def question_settings(self) -> Sequence[str]:
        return []

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["all_or_nothing", "partial"]

    def presets(self) -> Sequence[JSON]:
        return []

    def initial(self, preset: str, locales: Sequence[str]) -> JSON:
        return {}

    def validate_definition(self, config: JSON, locale: str) -> None:
        prompt = str(config.get("prompt", {}).get(locale, ""))
        if not prompt.strip():
            raise ValueError("the question text is missing")
        if _repeats_a_marker(prompt):
            raise ValueError(_repeat_message())
        expected = _all_markers(config)
        message = _markers_message(expected)
        if message is not None:
            raise ValueError(message)
        if _markers(prompt) != expected:
            raise ValueError(_("Every language must use the same blanks."))
        blanks = config.get("blanks", [])
        if len(blanks) != max(len(expected), 1):
            raise ValueError(_("Every blank needs its accepted answers."))
        if any(not blank.get("accepted", {}).get(locale) for blank in blanks):
            raise ValueError(_("Every blank needs its accepted answers."))
        if not has_alt(config.get("image"), locale):
            raise ValueError(_("An image has no description in this language."))

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        if not isinstance(answer, Mapping):
            raise ValueError("an answer must be a form")
        known = {f"blank_{number}" for number in range(1, len(config["blanks"]) + 1)}
        for key, value in answer.items():
            if not key.startswith("blank_"):
                continue
            if key not in known or not isinstance(value, str) or len(value) > MAX_ANSWER:
                raise ValueError("unknown blank")

    def grade(self, config: JSON, answer: JSON) -> ItemGrade:
        """A wrong blank is not a wrong tick, so nothing is subtracted."""
        switches = comparison(config)
        blanks = config["blanks"]
        right = 0
        for number, blank in enumerate(blanks, start=1):
            given = normalized(_value_of(answer, number), **switches)
            accepted = {
                normalized(text, **switches)
                for texts in blank.get("accepted", {}).values()
                for text in texts
            }
            right += bool(given) and given in accepted
        return ItemGrade(right, 0, len(blanks))

    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        """By the question's own comparison, so what grading treats alike counts together."""
        switches = comparison(config)
        several = len(config["blanks"]) > 1
        pairs = []
        for answer in answers:
            for number in range(1, len(config["blanks"]) + 1):
                written = _value_of(answer, number).strip()
                if not written:
                    continue
                key = normalized(written, **switches)
                if several:
                    blank = _("Blank %(number)s") % {"number": number}
                    pairs.append((f"{number}:{key}", f"{blank}: {written}"))
                else:
                    pairs.append((key, written))
        return counted(pairs)

    def file_fields(self, config: JSON) -> Sequence[str]:
        return []

    def needs_grading(self, config: JSON, answer: JSON | None) -> bool:
        return False

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        prompt = {locale: form_value(form, f"prompt_{locale}") for locale in locales}
        numbers = {number for text in prompt.values() for number in _markers(text)}
        count = max(numbers, default=1)
        blanks: list[dict[str, Any]] = []
        beyond = False
        for number in range(1, MAX_BLANKS + 1):
            accepted = {
                locale: _lines(form_value(form, f"accepted_{number}_{locale}"))
                for locale in locales
            }
            if number <= count:
                id_ = form_value(form, f"blank_{number}_id") or secrets.token_hex(4)
                blanks.append({"id": id_, "accepted": accepted})
            else:
                beyond = beyond or any(accepted.values())
        config: dict[str, Any] = {
            "prompt": prompt,
            "blanks": blanks,
            **{switch: bool(form_value(form, switch)) for switch in SWITCHES},
        }
        image = read_image(form, "image", locales)
        if image:
            config["image"] = image
        message = _markers_message(numbers)
        if message is not None:
            raise AdminFormError(message, config)
        if any(_repeats_a_marker(text) for text in prompt.values()):
            raise AdminFormError(_repeat_message(), config)
        if beyond:
            message = _("A row of answers has no blank in the question's text.")
            raise AdminFormError(message, config)
        return config

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]:
        return [
            *(f"prompt_{locale}" for locale in locales),
            *(
                f"answer_{number}_{locale}"
                for number in range(1, MAX_BLANKS + 1)
                for locale in locales
            ),
            *SWITCHES,
            "image",
            *(f"image_alt_{locale}" for locale in locales),
        ]

    def from_csv(self, cells: Mapping[str, str], locales: Sequence[str]) -> JSON:
        """Builds the editor's form, so a file is refused for what the editor refuses."""
        form: dict[str, list[str]] = {
            f"prompt_{locale}": [cells.get(f"prompt_{locale}", "")] for locale in locales
        }
        if not any(value[0].strip() for value in form.values()):
            raise CsvRowError(None, _("The question has no text in any language."))
        for number in range(1, MAX_BLANKS + 1):
            for locale in locales:
                form[f"accepted_{number}_{locale}"] = [cells.get(f"answer_{number}_{locale}", "")]
        for switch in SWITCHES:
            value = cells.get(switch, "").strip().lower()
            if value in ("true", "1", "yes") or (not value and DEFAULTS[switch]):
                form[switch] = ["on"]
            elif value not in ("", "false", "0", "no"):
                raise CsvRowError(switch, _("Write true or false here."))
        csv_image_form(form, cells, "image", "image", locales)
        try:
            config = self.parse_admin(form, locales)
        except AdminFormError as error:
            raise CsvRowError(f"prompt_{locales[0]}", str(error)) from error
        for number, blank in enumerate(config["blanks"], start=1):
            if not any(blank["accepted"].values()):
                column = f"answer_{number}_{locales[0]}"
                raise CsvRowError(column, _("Every blank needs its accepted answers."))
        return config

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]:
        prompt = config.get("prompt") or {}
        switches = comparison(config)
        return {
            **{f"prompt_{locale}": str(prompt.get(locale, "")) for locale in locales},
            **{
                f"answer_{number}_{locale}": "\n".join(blank["accepted"].get(locale, []))
                for number, blank in enumerate(config.get("blanks", []), start=1)
                for locale in locales
            },
            **{switch: "true" if switches[switch] else "false" for switch in SWITCHES},
            **csv_image_cells(config.get("image"), "image", locales),
        }

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        blanks = list(config.get("blanks", []))
        rows = [
            {
                "number": number,
                "id": blanks[number - 1]["id"] if number <= len(blanks) else "",
                "accepted": blanks[number - 1]["accepted"] if number <= len(blanks) else {},
            }
            for number in range(1, MAX_BLANKS + 1)
        ]
        return render_to_string(
            "text/admin.html",
            {
                "prompt": config.get("prompt", {}),
                "image": config.get("image"),
                "rows": rows,
                "used": max(len(blanks), 1),
                "locales": locales,
                **comparison(config),
            },
        )

    def render_public(self, public_config: JSON, locale: str, answer: JSON | None = None) -> str:
        values = {
            number: _value_of(answer, number) for number in range(1, public_config["blanks"] + 1)
        }
        return render_to_string(
            "text/public.html", {"q": public_config, "values": values, "max_length": MAX_ANSWER}
        )

    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str:
        blanks = config.get("blanks", [])
        rows = [
            {
                "number": number,
                "accepted": ", ".join(blank.get("accepted", {}).get(locale, [])),
                "theirs": _value_of(answer, number),
            }
            for number, blank in enumerate(blanks, start=1)
        ]
        return render_to_string("text/solution.html", {"rows": rows, "several": len(rows) > 1})

    def describe_definition(self, config: JSON, locales: Sequence[str]) -> list[DefinitionRow]:
        prompt = config.get("prompt", {})
        switches = comparison(config)
        rows = [DefinitionRow("prompt", _("Question"), lo, prompt.get(lo, "")) for lo in locales]
        rows += image_rows("image", config.get("image"), locales, _labels())
        for number, blank in enumerate(config.get("blanks", []), start=1):
            label = _("Accepted answers for blank %(number)s") % {"number": number}
            rows += [
                DefinitionRow(
                    f"blank:{blank['id']}", label, lo, ", ".join(blank["accepted"].get(lo, []))
                )
                for lo in locales
            ]
        names = {
            "ignore_case": _("Ignore letter case"),
            "ignore_spaces": _("Ignore extra spaces"),
            "ignore_diacritics": _("Ignore diacritics"),
        }
        for switch in SWITCHES:
            value = _("Yes") if switches[switch] else _("No")
            rows.append(DefinitionRow(switch, names[switch], None, value))
        return rows

    def public_payload(self, config: JSON, locale: str, quiz_settings: JSON | None = None) -> JSON:
        prompt = str(config["prompt"].get(locale, ""))
        payload: dict[str, Any] = {
            "prompt": _literal(prompt),
            "blanks": len(config["blanks"]),
            "segments": _segments(prompt) if _markers(prompt) else [],
        }
        image = public_image(config.get("image"), locale)
        if image:
            payload["image"] = image
        return payload
