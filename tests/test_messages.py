"""The compiled catalogues are reproducible: same bytes on every build."""

import shutil
from pathlib import Path

import pytest

from tools import messages

LOCALE_FILES = ("django.po", "django.mo")


def _copy(root: Path, target: Path) -> Path:
    shutil.copytree(root, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


IDS = [str(root.relative_to(messages.REPO)) for root in messages.ROOTS]


@pytest.mark.parametrize("root", messages.ROOTS, ids=IDS)
def test_committed_catalogues_are_reproducible(root: Path, tmp_path: Path) -> None:
    copy = _copy(root, tmp_path / "root")
    for locale in messages.LOCALES:
        messages.build(copy, locale)
        for name in LOCALE_FILES:
            relative = Path("locale") / locale / "LC_MESSAGES" / name
            assert (copy / relative).read_bytes() == (root / relative).read_bytes(), relative


def test_two_builds_give_the_same_mo(tmp_path: Path) -> None:
    root = messages.ROOTS[0]
    first = _copy(root, tmp_path / "a")
    second = _copy(root, tmp_path / "b")
    path = Path("locale") / "cs" / "LC_MESSAGES" / "django.mo"
    messages.build(first, "cs")
    messages.build(second, "cs")
    assert (first / path).read_bytes() == (second / path).read_bytes()
