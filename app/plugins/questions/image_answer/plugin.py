"""A photo as the answer: part of the points come automatically, the rest from a person.

The automatic part is a share of the question's points, so a draw row's points work as well, and
`partial` pays it through the ordinary grade (ADR-0047). The file reaches the plugin as an asset id,
which the API alone puts there.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.template.loader import render_to_string
from django.utils.translation import gettext as _

from app.contracts import (
    JSON,
    PHOTO_PUBLIC,
    PHOTO_VISIBILITY,
    AdminFormError,
    AnswerCount,
    CsvRowError,
    DefinitionRow,
    ItemGrade,
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

IMAGE = "image"
PERCENT = 100
ASSET = re.compile(r"[0-9a-fA-F-]{32,36}", re.ASCII)
WHOLE = re.compile(r"[0-9]{1,6}", re.ASCII)


def _labels() -> ImageLabels:
    return ImageLabels(_("Image"), _("No copy"), _("Image address"), _("Image description"))


def _whole(text: str) -> int | None:
    """Empty is zero. None when it cannot be read."""
    if not text:
        return 0
    return int(text) if WHOLE.fullmatch(text) else None


def _auto_from_form(form: Mapping[str, Sequence[str]]) -> dict[str, int] | str:
    """The share, or what to tell the admin. A bank has no points: its draw rows give them."""
    if "points" in form:
        total = _whole(form_value(form, "points"))
        right = _whole(form_value(form, "auto_points"))
        if right is None or not total or right > total:
            return _("Automatic points must be a whole number, up to the question's points.")
        return {"right": right, "total": total}
    right = _whole(form_value(form, "auto_percent"))
    if right is None or right > PERCENT:
        return _("The automatic share must be a whole number from 0 to 100.")
    return {"right": right, "total": PERCENT}


def _has_image(answer: Any) -> bool:
    value = answer.get(IMAGE) if isinstance(answer, Mapping) else None
    return isinstance(value, str) and bool(value)


class ImageAnswerQuestion:
    id = "image_answer"
    version = "1.0.0"

    def label(self) -> str:
        return _("Photo")

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "auto"]}

    def answer_schema(self) -> JSON:
        return {"type": "object", "properties": {IMAGE: {"type": "string"}}}

    def question_settings(self) -> Sequence[str]:
        return [PHOTO_VISIBILITY]

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["partial"]

    def presets(self) -> Sequence[JSON]:
        return []

    def initial(self, preset: str, locales: Sequence[str]) -> JSON:
        return {}

    def validate_definition(self, config: JSON, locale: str) -> None:
        if not str(config.get("prompt", {}).get(locale, "")).strip():
            raise ValueError("the question text is missing")
        auto = config.get("auto") or {}
        if not 0 <= int(auto.get("right", -1)) <= int(auto.get("total", 0)) or not auto["total"]:
            raise ValueError(_("The automatic part must fit within the question's points."))
        if not has_alt(config.get("image"), locale):
            raise ValueError(_("An image has no description in this language."))

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        if not isinstance(answer, Mapping):
            raise ValueError("an answer must be a form")
        value = answer.get(IMAGE, "")
        if not isinstance(value, str) or (value and not ASSET.fullmatch(value)):
            raise ValueError("not a stored image")

    def grade(self, config: JSON, answer: JSON) -> ItemGrade:
        auto = config["auto"]
        return ItemGrade(auto["right"] if _has_image(answer) else 0, 0, auto["total"])

    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        """A photo cannot be counted, and showing one is the admin's decision about that photo."""
        return []

    def file_fields(self, config: JSON) -> Sequence[str]:
        return [IMAGE]

    def needs_grading(self, config: JSON, answer: JSON | None) -> bool:
        return _has_image(answer)

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        config: dict[str, Any] = {
            "prompt": {locale: form_value(form, f"prompt_{locale}") for locale in locales},
        }
        image = read_image(form, "image", locales)
        if image:
            config["image"] = image
        auto = _auto_from_form(form)
        if isinstance(auto, str):
            config["auto"] = {"right": 0, "total": PERCENT}
            raise AdminFormError(auto, config)
        config["auto"] = auto
        return config

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]:
        return [
            *(f"prompt_{locale}" for locale in locales),
            "auto_points",
            "auto_share",
            "image",
            *(f"image_alt_{locale}" for locale in locales),
        ]

    def from_csv(self, cells: Mapping[str, str], locales: Sequence[str]) -> JSON:
        """Builds the editor's form. Automatic points need the question's points beside them."""
        form: dict[str, list[str]] = {
            f"prompt_{locale}": [cells.get(f"prompt_{locale}", "")] for locale in locales
        }
        if not any(value[0].strip() for value in form.values()):
            raise CsvRowError(None, _("The question has no text in any language."))
        points = cells.get("auto_points", "").strip()
        column = "auto_points" if points else "auto_share"
        if points:
            if not cells.get("points", "").strip():
                raise CsvRowError("points", _("Automatic points need the question's points."))
            form["points"] = [cells["points"]]
            form["auto_points"] = [points]
        else:
            form["auto_percent"] = [cells.get("auto_share", "")]
        csv_image_form(form, cells, "image", "image", locales)
        try:
            return self.parse_admin(form, locales)
        except AdminFormError as error:
            raise CsvRowError(column, str(error)) from error

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]:
        prompt = config.get("prompt") or {}
        auto = config.get("auto") or {"right": 0, "total": PERCENT}
        is_share = auto["total"] == PERCENT
        return {
            **{f"prompt_{locale}": str(prompt.get(locale, "")) for locale in locales},
            "auto_points": "" if is_share else str(auto["right"]),
            "auto_share": str(auto["right"]) if is_share else "",
            **csv_image_cells(config.get("image"), "image", locales),
        }

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        auto = config.get("auto") or {}
        total = auto.get("total") or PERCENT
        return render_to_string(
            "image_answer/admin.html",
            {
                "prompt": config.get("prompt", {}),
                "image": config.get("image"),
                "locales": locales,
                "auto_points": auto.get("right", 0),
                "auto_percent": round(auto.get("right", 0) * PERCENT / total),
            },
        )

    def render_public(self, public_config: JSON, locale: str, answer: JSON | None = None) -> str:
        return render_to_string(
            "image_answer/public.html", {"q": public_config, "sent": _has_image(answer)}
        )

    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str:
        prompt = config.get("prompt", {}).get(locale, "")
        return render_to_string("image_answer/solution.html", {"prompt": prompt})

    def describe_definition(self, config: JSON, locales: Sequence[str]) -> list[DefinitionRow]:
        prompt = config.get("prompt", {})
        auto = config.get("auto") or {}
        share = f"{auto.get('right', 0)} / {auto.get('total', 0)}"
        return [
            *[DefinitionRow("prompt", _("Question"), lo, prompt.get(lo, "")) for lo in locales],
            *image_rows("image", config.get("image"), locales, _labels()),
            DefinitionRow("auto", _("Automatic part"), None, share),
        ]

    def public_payload(self, config: JSON, locale: str, quiz_settings: JSON | None = None) -> JSON:
        visibility = (quiz_settings or {}).get(PHOTO_VISIBILITY)
        payload: dict[str, Any] = {
            "prompt": config["prompt"].get(locale, ""),
            "may_be_public": visibility == PHOTO_PUBLIC,
        }
        image = public_image(config.get("image"), locale)
        if image:
            payload["image"] = image
        return payload
