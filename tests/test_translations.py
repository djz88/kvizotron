"""Catalogues: complete where required, compiled, and in step with the code."""

from pathlib import Path

import pytest
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

from tools import messages

CATALOGUES = [
    (root, locale, root / "locale" / locale / "LC_MESSAGES")
    for root in messages.ROOTS
    for locale in messages.LOCALES
]
IDS = [f"{root.name}-{locale}" for root, locale, _ in CATALOGUES]


def read(path: Path):
    with path.open("rb") as file:
        return read_po(file) if path.suffix == ".po" else read_mo(file)


def is_admin_only(message) -> bool:
    return bool(message.locations) and all("admin" in loc for loc, _ in message.locations)


@pytest.mark.parametrize(("root", "locale", "directory"), CATALOGUES, ids=IDS)
def test_catalogue_has_no_empty_translation(root, locale, directory):
    """Admin UI is cs/en (FR-04), so only strings used solely in admin may lack Ukrainian."""
    empty = [
        m.id
        for m in read(directory / "django.po")
        if m.id and not m.string and not (locale == "uk" and is_admin_only(m))
    ]
    assert empty == []


@pytest.mark.parametrize(("root", "locale", "directory"), CATALOGUES, ids=IDS)
def test_compiled_catalogue_matches_source(root, locale, directory):
    source = {m.id: m.string for m in read(directory / "django.po") if m.id and m.string}
    compiled = {m.id: m.string for m in read(directory / "django.mo") if m.id}
    assert compiled == source


@pytest.mark.parametrize("root", messages.ROOTS, ids=lambda r: r.name)
@pytest.mark.parametrize("locale", messages.LOCALES)
def test_catalogue_contains_every_string_in_the_code(root, locale):
    known = {m.id for m in read(root / "locale" / locale / "LC_MESSAGES" / "django.po")}
    assert {m.id for m in messages.extract(root) if m.id} <= known
