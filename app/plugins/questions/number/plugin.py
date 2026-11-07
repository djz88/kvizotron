"""A numeric answer with an optional tolerance. Values are compared as exact decimals."""

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
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

NONE = "none"
ABSOLUTE = "absolute"
PERCENT = "percent"
KINDS = (NONE, ABSOLUTE, PERCENT)
MAX_DIGITS = 30
NUMBER = re.compile(r"-?\d+([.,]\d+)?", re.ASCII)


def parse_number(text: str) -> Decimal:
    """Digits, a minus sign and one separator, so exponents, NaN and infinity never get here."""
    value = text.strip()
    if not NUMBER.fullmatch(value) or sum(char.isdigit() for char in value) > MAX_DIGITS:
        raise ValueError("not a number")
    return Decimal(value.replace(",", "."))


def _limits(config: JSON) -> tuple[Decimal, Decimal]:
    correct = parse_number(str(config.get("value", "")))
    kind = config.get("tolerance_kind", NONE)
    if kind == NONE:
        return correct, correct
    tolerance = parse_number(str(config.get("tolerance", "")))
    with localcontext(prec=2 * MAX_DIGITS + 4):
        margin = tolerance if kind == ABSOLUTE else abs(correct) * tolerance / 100
        return correct - margin, correct + margin


def _shown(value: Any, locale: str) -> str:
    text = str(value)
    return text if locale == "en" else text.replace(".", ",")


def _tolerance_message(config: JSON) -> str | None:
    """What is wrong with the value and tolerance, for the editor and for publication."""
    try:
        correct = parse_number(str(config.get("value", "")))
    except ValueError:
        return _("The correct value must be a number, such as 3,14.")
    kind = config.get("tolerance_kind", NONE)
    if kind not in KINDS:
        return _("This kind of tolerance is not known.")
    if kind == NONE:
        return None
    try:
        tolerance = parse_number(str(config.get("tolerance", "")))
    except ValueError:
        return _("The tolerance must be a number, such as 0,5.")
    if tolerance < 0:
        return _("The tolerance cannot be negative.")
    if kind == PERCENT and correct == 0:
        return _("A tolerance in percent cannot be used when the correct value is 0.")
    return None


def _labels() -> ImageLabels:
    return ImageLabels(_("Image"), _("No copy"), _("Image address"), _("Image description"))


def _kind_label(kind: str) -> str:
    return {NONE: _("Exact value"), ABSOLUTE: _("Plus or minus"), PERCENT: _("Percent")}.get(
        kind, kind
    )


def _written(text: str) -> str:
    """A readable value in its stored form; anything else is left for the message to name."""
    try:
        parse_number(text)
    except ValueError:
        return text
    return text.strip().replace(",", ".")


class NumberQuestion:
    id = "number"
    version = "1.0.0"

    def label(self) -> str:
        return _("Number")

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "value", "tolerance_kind"]}

    def answer_schema(self) -> JSON:
        return {"type": "object", "properties": {"value": {"type": "string"}}}

    def question_settings(self) -> Sequence[str]:
        return []

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["all_or_nothing"]

    def presets(self) -> Sequence[JSON]:
        return []

    def initial(self, preset: str, locales: Sequence[str]) -> JSON:
        return {}

    def validate_definition(self, config: JSON, locale: str) -> None:
        if not str(config.get("prompt", {}).get(locale, "")).strip():
            raise ValueError("the question text is missing")
        message = _tolerance_message(config)
        if message is not None:
            raise ValueError(message)
        if not has_alt(config.get("image"), locale):
            raise ValueError(_("An image has no description in this language."))

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        if not isinstance(answer, Mapping):
            raise ValueError("an answer must be a form")
        value = answer.get("value", "")
        if not isinstance(value, str):
            raise ValueError("a value must be text")
        if value.strip():
            parse_number(value)

    def grade(self, config: JSON, answer: JSON) -> ItemGrade:
        value = answer.get("value", "") if isinstance(answer, Mapping) else ""
        if not isinstance(value, str) or not value.strip():
            return ItemGrade(0, 0, 1)
        try:
            number = parse_number(value)
        except ValueError:
            return ItemGrade(0, 1, 1)
        low, high = _limits(config)
        return ItemGrade(1, 0, 1) if low <= number <= high else ItemGrade(0, 1, 1)

    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        """Equal numbers count together, however they were written."""
        pairs = []
        for answer in answers:
            value = answer.get("value", "") if isinstance(answer, Mapping) else ""
            try:
                number = f"{parse_number(str(value)).normalize():f}"
            except ValueError:
                continue
            pairs.append((number, _shown(number, locale)))
        return counted(pairs)

    def file_fields(self, config: JSON) -> Sequence[str]:
        return []

    def needs_grading(self, config: JSON, answer: JSON | None) -> bool:
        return False

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        kind = form_value(form, "tolerance_kind") or NONE
        tolerance = form_value(form, "tolerance")
        if not tolerance and kind in (ABSOLUTE, PERCENT):
            kind = NONE
        config: dict[str, Any] = {
            "prompt": {locale: form_value(form, f"prompt_{locale}") for locale in locales},
            "value": _written(form_value(form, "value")),
            "tolerance": "" if kind == NONE else _written(tolerance),
            "tolerance_kind": kind,
        }
        image = read_image(form, "image", locales)
        if image:
            config["image"] = image
        if config["value"]:
            message = _tolerance_message(config)
            if message is not None:
                raise AdminFormError(message, config)
        return config

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]:
        return [
            *(f"prompt_{locale}" for locale in locales),
            "correct_value",
            "tolerance",
            "tolerance_kind",
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
        if not cells.get("correct_value", "").strip():
            raise CsvRowError("correct_value", _("The correct value is missing."))
        tolerance = cells.get("tolerance", "").strip()
        form["value"] = [cells.get("correct_value", "")]
        form["tolerance"] = [tolerance]
        form["tolerance_kind"] = [
            cells.get("tolerance_kind", "").strip() or (ABSOLUTE if tolerance else NONE)
        ]
        csv_image_form(form, cells, "image", "image", locales)
        try:
            return self.parse_admin(form, locales)
        except AdminFormError as error:
            raise CsvRowError("correct_value", str(error)) from error

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]:
        prompt = config.get("prompt") or {}
        return {
            **{f"prompt_{locale}": str(prompt.get(locale, "")) for locale in locales},
            "correct_value": str(config.get("value", "")),
            "tolerance": str(config.get("tolerance", "")),
            "tolerance_kind": str(config.get("tolerance_kind", NONE)),
            **csv_image_cells(config.get("image"), "image", locales),
        }

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        return render_to_string(
            "number/admin.html",
            {
                "prompt": config.get("prompt", {}),
                "image": config.get("image"),
                "value": config.get("value", ""),
                "tolerance": config.get("tolerance", ""),
                "kind": config.get("tolerance_kind", NONE),
                "locales": locales,
            },
        )

    def render_public(self, public_config: JSON, locale: str, answer: JSON | None = None) -> str:
        value = answer.get("value", "") if isinstance(answer, Mapping) else ""
        return render_to_string("number/public.html", {"q": public_config, "value": value})

    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str:
        value = answer.get("value", "") if isinstance(answer, Mapping) else ""
        return render_to_string(
            "number/solution.html",
            {
                "value": _shown(config.get("value", ""), locale),
                "tolerance": _shown(config.get("tolerance", ""), locale),
                "kind": config.get("tolerance_kind", NONE),
                "theirs": value if isinstance(value, str) else "",
            },
        )

    def describe_definition(self, config: JSON, locales: Sequence[str]) -> list[DefinitionRow]:
        prompt = config.get("prompt", {})
        kind = str(config.get("tolerance_kind", NONE))
        return [
            *[DefinitionRow("prompt", _("Question"), lo, prompt.get(lo, "")) for lo in locales],
            *image_rows("image", config.get("image"), locales, _labels()),
            DefinitionRow("value", _("Correct value"), None, str(config.get("value", ""))),
            DefinitionRow("tolerance", _("Tolerance"), None, str(config.get("tolerance", ""))),
            DefinitionRow("tolerance_kind", _("Kind of tolerance"), None, _kind_label(kind)),
        ]

    def public_payload(self, config: JSON, locale: str, quiz_settings: JSON | None = None) -> JSON:
        payload: dict[str, Any] = {"prompt": config["prompt"].get(locale, "")}
        image = public_image(config.get("image"), locale)
        if image:
            payload["image"] = image
        return payload
