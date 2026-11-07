"""The optional image of a question, shared by question types, which may not import each other."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.contracts import JSON, DefinitionRow


@dataclass(frozen=True)
class ImageLabels:
    """Translated by the calling plugin, as this module cannot use Django."""

    image: str
    no_copy: str
    address: str
    description: str


def form_value(form: Mapping[str, Sequence[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[-1].strip()


def read_image(form: Mapping[str, Sequence[str]], name: str, locales: Sequence[str]) -> JSON | None:
    """The API stores a file or fetches an address first and hands over `<name>_asset`.

    After a refused file the form comes back unsaved, and the row keeps what was typed for it.
    An address that could not be fetched may stay without an asset.
    """
    asset = form_value(form, f"{name}_asset")
    source = form_value(form, f"{name}_source")
    refused = bool(form_value(form, f"{name}_refused"))
    if (not asset and not source and not refused) or form_value(form, f"{name}_remove"):
        return None
    image: dict[str, Any] = {
        "asset": asset or None,
        "alt": {lo: form_value(form, f"{name}_alt_{lo}") for lo in locales},
    }
    if source:
        image["source"] = source
    return image


def public_image(image: JSON | None, locale: str) -> JSON | None:
    """The API decides between the two and passes on neither."""
    if not image:
        return None
    public = {"asset": image.get("asset"), "alt": image["alt"].get(locale, "")}
    return public | ({"source": image["source"]} if image.get("source") else {})


def image_rows(
    key: str, image: JSON | None, locales: Sequence[str], labels: ImageLabels
) -> list[DefinitionRow]:
    if not image:
        return []
    copy = str(image["asset"])[-12:] if image.get("asset") else labels.no_copy
    address = (
        [DefinitionRow(f"{key}_source", labels.address, None, image["source"])]
        if image.get("source")
        else []
    )
    return [
        DefinitionRow(key, labels.image, None, copy),
        *address,
        *[
            DefinitionRow(f"{key}_alt", labels.description, lo, image["alt"].get(lo, ""))
            for lo in locales
        ],
    ]


def has_alt(image: JSON | None, locale: str) -> bool:
    return not image or bool(str(image["alt"].get(locale, "")).strip())


def csv_image_form(
    form: dict[str, list[str]],
    cells: Mapping[str, str],
    name: str,
    column: str,
    locales: Sequence[str],
) -> None:
    source = cells.get(column, "").strip()
    if source:
        form[f"{name}_source"] = [source]
    for locale in locales:
        form[f"{name}_alt_{locale}"] = [cells.get(f"{column}_alt_{locale}", "")]


def csv_image_cells(image: JSON | None, column: str, locales: Sequence[str]) -> dict[str, str]:
    if not image:
        return {}
    alt = image.get("alt") or {}
    return {
        column: str(image.get("source") or ""),
        **{f"{column}_alt_{locale}": str(alt.get(locale, "")) for locale in locales},
    }
