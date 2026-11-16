"""Catalogues: complete where required, compiled, and in step with the code."""

import re
from pathlib import Path

import pytest
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po
from django.utils import translation

from app.kernel.discovery import installed_modules
from tools import messages

CATALOGUES = [
    (root, locale, root / "locale" / locale / "LC_MESSAGES")
    for root in messages.ROOTS
    for locale in messages.LOCALES
]
IDS = [f"{root.name}-{locale}" for root, locale, _ in CATALOGUES]


def read(path: Path):
    with path.open("rb") as file:
        if path.suffix != ".po":
            return read_mo(file)
        # The catalogues have no header, so the plural count comes from the locale directory.
        return read_po(file, locale=path.parent.parent.name)


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
    def key(value):  # a plural message has a list in the .mo and a tuple in the .po
        return tuple(value) if isinstance(value, (list, tuple)) else value

    source = {key(m.id): key(m.string) for m in read(directory / "django.po") if m.id and m.string}
    compiled = {key(m.id): key(m.string) for m in read(directory / "django.mo") if m.id}
    assert compiled == source


@pytest.mark.parametrize("root", messages.ROOTS, ids=lambda r: r.name)
@pytest.mark.parametrize("locale", messages.LOCALES)
def test_catalogue_contains_every_string_in_the_code(root, locale):
    known = {m.id for m in read(root / "locale" / locale / "LC_MESSAGES" / "django.po")}
    assert {m.id for m in messages.extract(root) if m.id} <= known


OLD_WORD = re.compile(r"(?i)\b(rounds?|kolo|kola|kolu|kole|раунд\w*)\b")


def test_catalogues_do_not_use_the_old_word_for_a_run():
    found = [
        text
        for root, _locale, directory in CATALOGUES
        for message in read(directory / "django.po")
        for text in (message.id, message.string)
        if text and OLD_WORD.search(str(text))
    ]
    assert found == []


def test_every_text_of_a_manifest_is_translated():
    """Settings and requirements are shown to admins, and a manifest cannot call gettext."""
    missing = []
    for module in installed_modules():
        texts = [
            text
            for declared in module.settings
            for text in (declared.label, declared.help, *declared.value_labels.values())
            if text
        ]
        texts += [item.reason for item in module.settings_requirements.values()]
        texts += [text for text in (module.name, module.description) if text]
        for text in texts:
            if text.isdigit():
                continue  # a number reads the same in every language
            with translation.override("cs"):
                if translation.gettext(text) == text:  # noqa: INT001
                    missing.append(f"{module.id}: {text}")
    assert missing == []
