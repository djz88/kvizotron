"""Directions of imports between parts of the application (app/CLAUDE.md)."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
ALLOWED = {
    "contracts": {"contracts"},
    "kernel": {"contracts", "kernel"},
    "domain": {"contracts", "kernel", "domain"},
    "api": {"contracts", "kernel", "domain", "api"},
    "plugins": {"contracts", "kernel", "plugins"},
    "providers": {"contracts", "kernel", "providers"},
}


def imported_parts(path: Path) -> set[str]:
    parts = set()
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
            if node.module == "app":
                names = [f"app.{alias.name}" for alias in node.names]
        parts |= {name.split(".")[1] for name in names if name.startswith("app.")}
    return parts


@pytest.mark.parametrize("part", ALLOWED)
def test_imports_follow_the_layers(part):
    wrong = {
        f"{path.relative_to(APP)} imports app.{other}"
        for path in (APP / part).rglob("*.py")
        for other in imported_parts(path) - ALLOWED[part]
    }
    assert not wrong


def test_contracts_do_not_import_django():
    tree = ast.parse((APP / "contracts" / "__init__.py").read_text())
    modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {name for name in modules if name.split(".")[0] == "django"}
