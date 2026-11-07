"""Choice (FR-15): one, several or no correct answers, and yes/no.

Option ids say nothing about which option is correct. One answer is the default, with radio
buttons; the admin may allow several, with checkboxes that say nothing about how many are correct.
"""

import random
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from django.template.loader import render_to_string
from django.utils import translation
from django.utils.translation import gettext as _

from app.contracts import (
    EXTERNAL_IMAGE_MODE,
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
    has_alt,
    image_rows,
    public_image,
    read_image,
)

MAX_OPTIONS = 6
LETTERS = "ABCDEF"
MIN_OPTIONS = 2
STANDARD = "standard"
YES_NO = "yes_no"
YES_NO_ROWS = 2
NONE = "none"  # the value of "None of the answers" among radio buttons; option ids are hex
ALL_QUESTIONS = "all_questions"
TRICK_QUESTIONS = "trick_questions"


def _value(form: Mapping[str, Sequence[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1].strip()


def _same_text(options: Sequence[Mapping], locale: str) -> str | None:
    """Two options a participant cannot tell apart. Case and extra spaces make no difference."""
    seen = set()
    for option in options:
        text = str(option["text"].get(locale, ""))
        key = " ".join(text.split()).casefold()
        if key and key in seen:
            return text
        seen.add(key)
    return None


def _same_text_message(text: str) -> str:
    return _("Two options have the same text: %(text)s") % {"text": text}


def _one_answer_message() -> str:
    return _("Several options are marked as correct. Allow participants to choose several answers.")


def _yes_no_message() -> str:
    return _("A yes/no question needs both answers and exactly one marked as correct.")


def _sent(answer: Any) -> list[str]:
    options = answer.get("options") if isinstance(answer, Mapping) else None
    return [o for o in options if isinstance(o, str)] if isinstance(options, list) else []


def _ticked(answer: Any) -> list[str]:
    return [option for option in _sent(answer) if option != NONE]


def _none_ticked(answer: Any) -> bool:
    return NONE in _sent(answer) or (isinstance(answer, Mapping) and answer.get("none") == "1")


def _image_labels() -> ImageLabels:
    return ImageLabels(_("Image"), _("No copy"), _("Image address"), _("Image description"))


def _csv_flag(cells: Mapping[str, str], column: str) -> bool | None:
    """None for a blank cell."""
    value = cells.get(column, "").strip().lower()
    if not value:
        return None
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise CsvRowError(column, _("Write true or false here."))


def _csv_letters(cells: Mapping[str, str]) -> set[int]:
    """`A,C` as row numbers, each checked against the options there really are."""
    rows = set()
    for token in cells.get("correct", "").split(","):
        letter = token.strip().upper()
        if not letter:
            continue
        row = LETTERS.find(letter)
        if len(letter) != 1 or row < 0:
            raise CsvRowError("correct", _("Name correct options by letter, like A or A,C."))
        rows.add(row)
    return rows


def _is_yes_no(config: JSON) -> bool:
    return config.get("kind") == YES_NO


def _allows_several(config: JSON) -> bool:
    return bool(config.get("allow_multiple")) and not _is_yes_no(config)


class ChoiceQuestion:
    id = "choice"
    version = "1.0.0"

    def label(self) -> str:
        return _("Choice")

    def config_schema(self) -> JSON:
        return {"type": "object", "required": ["prompt", "options", "correct"]}

    def answer_schema(self) -> JSON:
        return {
            "type": "object",
            "properties": {
                "options": {"type": "array", "items": {"type": "string"}},
                "none": {"const": "1"},
            },
        }

    def question_settings(self) -> Sequence[str]:
        return ["none_option", "shuffle_options", EXTERNAL_IMAGE_MODE]

    def available_scoring_strategies(self) -> Sequence[str]:
        return ["all_or_nothing", "partial"]

    def presets(self) -> Sequence[JSON]:
        return [{"id": YES_NO, "label": _("Yes or no")}]

    def initial(self, preset: str, locales: Sequence[str]) -> JSON:
        if preset != YES_NO:
            return {}
        options = []
        for text in ("Yes", "No"):
            translated = {}
            for locale in locales:
                with translation.override(locale):
                    translated[locale] = _(text)
            options.append({"id": secrets.token_hex(4), "text": translated})
        return {"prompt": {}, "options": options, "correct": [], "kind": YES_NO}

    def validate_definition(self, config: JSON, locale: str) -> None:
        if not str(config.get("prompt", {}).get(locale, "")).strip():
            raise ValueError("the question text is missing")
        options = config.get("options", [])
        if len(options) < MIN_OPTIONS:
            raise ValueError(f"at least {MIN_OPTIONS} options are needed")
        for option in options:
            if not self._option_is_complete(option, locale):
                raise ValueError("an option text is missing")
        images = [config.get("image"), *[o.get("image") for o in options]]
        if not all(has_alt(image, locale) for image in images):
            raise ValueError(_("An image has no description in this language."))
        same = _same_text(options, locale)
        if same is not None:
            raise ValueError(_same_text_message(same))
        correct = config.get("correct", [])
        if not set(correct) <= {o["id"] for o in options}:
            raise ValueError("a correct option does not exist")
        if _is_yes_no(config) and (len(options) != YES_NO_ROWS or len(correct) != 1):
            raise ValueError(_yes_no_message())
        if len(correct) > 1 and not _allows_several(config):
            raise ValueError(_one_answer_message())

    def _option_is_complete(self, option: JSON, locale: str) -> bool:
        """An image can stand alone, but text started in one language must be in all of them."""
        if str(option["text"].get(locale, "")).strip():
            return True
        return bool(option.get("image")) and not any(
            str(text).strip() for text in option["text"].values()
        )

    def validate_submission(self, config: JSON, answer: JSON) -> None:
        if not isinstance(answer, Mapping):
            raise ValueError("an answer must be a form")
        options = answer.get("options", [])
        if not isinstance(options, list):
            raise ValueError("options must be a list")
        known = {o["id"] for o in config["options"]}
        if any(not isinstance(o, str) or o not in known | {NONE} for o in options):
            raise ValueError("unknown option")
        if "none" in answer and answer["none"] != "1":
            raise ValueError("unknown value of none")
        chosen = set(options) | ({NONE} if "none" in answer else set())
        if len(chosen) > 1 and not _allows_several(config):
            raise ValueError("only one answer is allowed")

    def grade(self, config: JSON, answer: JSON) -> ItemGrade:
        """ "None" alone answers a trick question; anywhere else it is a wrong answer."""
        correct = set(config["correct"])
        ticked = set(_ticked(answer))
        wrong = len(ticked - correct)
        if not correct:
            right = int(_none_ticked(answer) and not ticked)
            return ItemGrade(right, wrong, 1)
        if _none_ticked(answer):
            return ItemGrade(0, wrong + 1, len(correct))
        return ItemGrade(len(ticked & correct), wrong, len(correct))

    def summarize(
        self, config: JSON, answers: Sequence[JSON], locale: str
    ) -> Sequence[AnswerCount]:
        texts = {option["id"]: option["text"].get(locale, "") for option in config["options"]}
        pairs = []
        for answer in answers:
            pairs += [(item, texts[item]) for item in _ticked(answer) if item in texts]
            if _none_ticked(answer):
                pairs.append((NONE, _("None of the answers")))
        return counted(pairs)

    def file_fields(self, config: JSON) -> Sequence[str]:
        return []

    def needs_grading(self, config: JSON, answer: JSON | None) -> bool:
        return False

    def parse_admin(self, form: Mapping[str, Sequence[str]], locales: Sequence[str]) -> JSON:
        options = []
        correct = []
        blank_marked = False
        for row in range(MAX_OPTIONS):
            text = {locale: _value(form, f"option_{row}_{locale}") for locale in locales}
            marked = bool(_value(form, f"correct_{row}"))
            image = read_image(form, f"option_{row}_image", locales)
            if not any(text.values()) and not image:
                blank_marked = blank_marked or marked
                continue
            option_id = _value(form, f"option_{row}_id") or secrets.token_hex(4)
            option: dict[str, Any] = {"id": option_id, "text": text}
            if image:
                option["image"] = image
            options.append(option)
            if marked:
                correct.append(option_id)
        kind = YES_NO if _value(form, "kind") == YES_NO else STANDARD
        several = kind == STANDARD and bool(_value(form, "allow_multiple"))
        config: dict[str, Any] = {
            "prompt": {locale: _value(form, f"prompt_{locale}") for locale in locales},
            "options": options,
            "correct": correct,
            "allow_multiple": several,
            "reveal_count": several and bool(_value(form, "reveal_count")),
            "kind": kind,
        }
        question_image = read_image(form, "image", locales)
        if question_image:
            config["image"] = question_image
        if blank_marked:
            raise AdminFormError(_("A row marked as correct has no text."), config)
        if kind == YES_NO and (len(options) != YES_NO_ROWS or len(correct) != 1):
            raise AdminFormError(_yes_no_message(), config)
        if len(correct) > 1 and not several:
            raise AdminFormError(_one_answer_message(), config)
        for locale in locales:
            same = _same_text(options, locale)
            if same is not None:
                raise AdminFormError(_same_text_message(same), config)
        return config

    def csv_columns(self, locales: Sequence[str]) -> Sequence[str]:
        columns = [f"prompt_{locale}" for locale in locales]
        columns += ["kind", "allow_multiple", "reveal_count", "correct", "image"]
        columns += [f"image_alt_{locale}" for locale in locales]
        for number in range(1, MAX_OPTIONS + 1):
            columns += [f"option_{number}_{locale}" for locale in locales]
            columns.append(f"option_{number}_image")
            columns += [f"option_{number}_image_alt_{locale}" for locale in locales]
        return columns

    def from_csv(self, cells: Mapping[str, str], locales: Sequence[str]) -> JSON:
        """Builds the editor's form, so a file is refused for what the editor refuses."""
        form: dict[str, list[str]] = {}
        for locale in locales:
            form[f"prompt_{locale}"] = [cells.get(f"prompt_{locale}", "")]
        if not any(value[0].strip() for value in form.values()):
            raise CsvRowError(None, _("The question has no text in any language."))
        marked = _csv_letters(cells)
        several = _csv_flag(cells, "allow_multiple")
        count = _csv_flag(cells, "reveal_count")
        filled = []
        for row in range(MAX_OPTIONS):
            number = row + 1
            for locale in locales:
                form[f"option_{row}_{locale}"] = [cells.get(f"option_{number}_{locale}", "")]
            csv_image_form(form, cells, f"option_{row}_image", f"option_{number}_image", locales)
            if row in marked:
                form[f"correct_{row}"] = ["1"]
            has_text = any(form[f"option_{row}_{locale}"][0].strip() for locale in locales)
            if has_text or f"option_{row}_image_source" in form:
                filled.append(row)
        if marked - set(filled):
            raise CsvRowError("correct", _("A letter names an option that has no text."))
        csv_image_form(form, cells, "image", "image", locales)
        form["kind"] = [cells.get("kind", "").strip() or STANDARD]
        if several or (several is None and len(marked) > 1):
            form["allow_multiple"] = ["1"]
        if count:
            form["reveal_count"] = ["1"]
        try:
            return self.parse_admin(form, locales)
        except AdminFormError as error:
            raise CsvRowError(None, str(error)) from error

    def to_csv(self, config: JSON, locales: Sequence[str]) -> Mapping[str, str]:
        options = list(config.get("options", []))
        correct = config.get("correct") or []
        prompt = config.get("prompt") or {}
        cells = {f"prompt_{locale}": str(prompt.get(locale, "")) for locale in locales}
        cells |= {
            "kind": str(config.get("kind", STANDARD)),
            "allow_multiple": "true" if _allows_several(config) else "false",
            "reveal_count": "true" if config.get("reveal_count") else "false",
            "correct": ",".join(
                LETTERS[row] for row, option in enumerate(options) if option["id"] in correct
            ),
        }
        cells |= csv_image_cells(config.get("image"), "image", locales)
        for row, option in enumerate(options):
            number = row + 1
            text = option.get("text") or {}
            cells |= {f"option_{number}_{lo}": str(text.get(lo, "")) for lo in locales}
            cells |= csv_image_cells(option.get("image"), f"option_{number}_image", locales)
        return cells

    def render_admin(self, config: JSON, locales: Sequence[str]) -> str:
        options = list(config.get("options", []))
        correct = config.get("correct") or []
        yes_no = _is_yes_no(config)
        rows = [
            {
                "index": index,
                "id": options[index]["id"] if index < len(options) else "",
                "text": options[index]["text"] if index < len(options) else {},
                "correct": index < len(options) and options[index]["id"] in correct,
                "image": options[index].get("image") if index < len(options) else None,
            }
            for index in range(YES_NO_ROWS if yes_no else MAX_OPTIONS)
        ]
        return render_to_string(
            "choice/admin.html",
            {
                "prompt": config.get("prompt", {}),
                "image": config.get("image"),
                "rows": rows,
                "locales": locales,
                "kind": YES_NO if yes_no else STANDARD,
                "allow_multiple": _allows_several(config),
                "reveal_count": bool(config.get("reveal_count")),
            },
        )

    def render_public(self, public_config: JSON, locale: str, answer: JSON | None = None) -> str:
        return render_to_string(
            "choice/public.html",
            {"q": public_config, "ticked": _ticked(answer), "none_ticked": _none_ticked(answer)},
        )

    def render_solution(self, config: JSON, locale: str, answer: JSON | None) -> str:
        correct = config["correct"]
        ticked = _ticked(answer)
        options = []
        for option in config["options"]:
            image = option.get("image")
            options.append(
                {
                    "text": option["text"].get(locale, ""),
                    "correct": option["id"] in correct,
                    "ticked": option["id"] in ticked,
                    "image": {"url": image.get("url", ""), "alt": image["alt"].get(locale, "")}
                    if image
                    else None,
                }
            )
        context = {"options": options, "trick": not correct, "none_ticked": _none_ticked(answer)}
        return render_to_string("choice/solution.html", context)

    def describe_definition(self, config: JSON, locales: Sequence[str]) -> list[DefinitionRow]:
        """Options are numbered, so the description differs even when two texts are the same."""
        prompt = config.get("prompt", {})
        options = config.get("options", [])
        main = locales[0]
        numbered = [f"{n}: {o['text'].get(main, '')}" for n, o in enumerate(options, start=1)]
        rows = [DefinitionRow("prompt", _("Question"), lo, prompt.get(lo, "")) for lo in locales]
        rows += image_rows("image", config.get("image"), locales, _image_labels())
        for option in options:
            rows += [
                DefinitionRow(f"option:{option['id']}", _("Option"), lo, option["text"].get(lo, ""))
                for lo in locales
            ]
            key = f"option_image:{option['id']}"
            rows += image_rows(key, option.get("image"), locales, _image_labels())
        rows.append(DefinitionRow("order", _("Order of options"), None, ", ".join(numbered)))
        marked = config.get("correct") or []
        correct = [
            text for text, option in zip(numbered, options, strict=True) if option["id"] in marked
        ]
        rows.append(
            DefinitionRow(
                "correct", _("Correct"), None, ", ".join(correct) or _("None (trick question)")
            )
        )
        rows.append(
            DefinitionRow(
                "reveal_count",
                _("Show the number of correct answers"),
                None,
                _("Yes") if config.get("reveal_count") else _("No"),
            )
        )
        rows.append(
            DefinitionRow(
                "allow_multiple",
                _("Participants may choose several answers"),
                None,
                _("Yes") if _allows_several(config) else _("No"),
            )
        )
        kind = _("Yes or no") if _is_yes_no(config) else _("Choice")
        rows.append(DefinitionRow("kind", _("Kind"), None, kind))
        return rows

    def public_payload(self, config: JSON, locale: str, quiz_settings: JSON | None = None) -> JSON:
        """`quiz_settings` comes from the API, because a plugin does not read settings."""
        correct = config.get("correct") or []
        standard = not _is_yes_no(config)
        policy = (quiz_settings or {}).get("none_option")
        payload: dict[str, Any] = {
            "prompt": config["prompt"].get(locale, ""),
            "options": [
                {"id": option["id"], "text": option["text"].get(locale, "")}
                for option in config["options"]
            ],
            "multiple": _allows_several(config),
            "offer_none": standard
            and (policy == ALL_QUESTIONS or (policy == TRICK_QUESTIONS and not correct)),
        }
        if _allows_several(config) and correct and config.get("reveal_count"):
            payload["count"] = len(correct)
        if config.get("image"):
            payload["image"] = public_image(config["image"], locale)
        for option, public in zip(config["options"], payload["options"], strict=True):
            if option.get("image"):
                public["image"] = public_image(option["image"], locale)
        seed = (quiz_settings or {}).get("shuffle_seed")
        if seed and standard:
            random.Random(seed).shuffle(payload["options"])  # noqa: S311  # repeatable on purpose
        return payload
