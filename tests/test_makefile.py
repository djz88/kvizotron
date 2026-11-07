"""`make clean` removes what setup and the tools create, and nothing that matters."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REMOVED = (
    ".venv/bin/python",
    ".pytest_cache/x",
    ".ruff_cache/x",
    ".mypy_cache/x",
    ".coverage",
    "htmlcov/index.html",
    "dist/x.whl",
    "build/x",
    "__pycache__/x.pyc",
    "app/__pycache__/x.pyc",
    "deploy/__pycache__/x.pyc",
)

KEPT = (
    ".env",
    "deploy/.env",
    "kvizotron.sqlite3",
    "media/photo.jpg",
    "backups/x.sqlite3",
    "exports/x.csv",
    ".superpowers/sdd/progress.md",
    ".worktrees/topic/app/main.py",
    ".worktrees/topic/app/__pycache__/x.pyc",
    "report.md",
    "uv.lock",
    "app/main.py",
)


MAKE = shutil.which("make")


@pytest.mark.skipif(MAKE is None, reason="make is not installed")
def test_clean_removes_the_environment_and_keeps_the_rest(tmp_path: Path) -> None:
    assert MAKE is not None
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    for name in REMOVED + KEPT:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")

    subprocess.run([MAKE, "clean"], cwd=tmp_path, check=True, capture_output=True)

    assert [name for name in REMOVED if (tmp_path / name).exists()] == []
    assert [name for name in KEPT if not (tmp_path / name).exists()] == []
    assert not (tmp_path / ".venv").exists()
