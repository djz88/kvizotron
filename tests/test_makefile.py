"""`make clean` removes what setup and the tools create, and nothing that matters."""

import os
import re
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


def _make_dry(tmp_path: Path, target: str, pyproject: str) -> list[str]:
    assert MAKE is not None
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "pyproject.toml").write_text(pyproject)
    # Under `make test` the parent's MAKELEVEL would add "Entering directory" lines.
    env = {k: v for k, v in os.environ.items() if k not in {"MAKELEVEL", "MAKEFLAGS", "MFLAGS"}}
    shown = subprocess.run(
        [MAKE, "-n", target], cwd=tmp_path, env=env, check=True, capture_output=True, text=True
    ).stdout
    return shown.splitlines()


@pytest.mark.skipif(MAKE is None, reason="make is not installed")
def test_env_update_installs_every_declared_version(tmp_path: Path) -> None:
    """`make env-update` installs what the project declares, in order: uv, Python and
    packages, pre-commit and its hooks, the Docker images. Nothing is bumped to a newer version."""
    lines = _make_dry(tmp_path, "env-update", '[tool.uv]\nrequired-version = ">=0.13"\n')

    assert lines[0] == "uv self update 0.13.0"
    assert lines[1] == "uv sync --frozen"
    assert lines[2] == "uvx --python 3.14 pre-commit@4.7.0 install --install-hooks"
    assert "pull --ignore-buildable" in lines[3]
    assert "build --pull" in lines[4]
    assert all("deploy/compose.yaml" in line for line in lines[3:5])


@pytest.mark.skipif(MAKE is None, reason="make is not installed")
def test_hooks_and_secrets_use_the_pinned_pre_commit(tmp_path: Path) -> None:
    """No target runs whatever pre-commit happens to be on PATH."""
    pyproject = '[tool.uv]\nrequired-version = ">=0.13.7"\n'
    shown = _make_dry(tmp_path, "hooks", pyproject) + _make_dry(tmp_path, "secrets", pyproject)

    calls = [line for line in shown if "pre-commit" in line]

    assert len(calls) == 3
    assert all(line.startswith("uvx --python 3.14 pre-commit@4.7.0 ") for line in calls)
    assert "python3 tools/private_traces.py list || true" in shown


def test_the_image_installs_the_uv_the_project_declares() -> None:
    """One uv version: the Dockerfile pin equals `[tool.uv] required-version` in pyproject."""
    declared = re.search(
        r'^required-version = ">=([0-9.]+)"', (ROOT / "pyproject.toml").read_text(), re.M
    )
    pinned = re.search(r"uv==([0-9.]+)", (ROOT / "Dockerfile").read_text())
    assert declared and pinned
    assert declared.group(1) == pinned.group(1)


@pytest.mark.skipif(MAKE is None, reason="make is not installed")
def test_doctor_points_an_old_uv_to_env_update(tmp_path: Path) -> None:
    """An old uv is not replaced silently: doctor says which command installs the right one."""
    assert MAKE is not None
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "pyproject.toml").write_text('[tool.uv]\nrequired-version = ">=0.13.7"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\necho 'uv 0.13.2 (fake)'\n")
    uv.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}

    done = subprocess.run([MAKE, "doctor"], cwd=tmp_path, env=env, capture_output=True, text=True)

    assert done.returncode != 0
    assert "0.13.7" in done.stdout and "make env-update" in done.stdout


def test_load_is_a_documented_phony_target() -> None:
    """AC-139: `make load` shows in `make help` (a `##` comment) and is declared phony."""
    makefile = (ROOT / "Makefile").read_text()
    phony = next(line for line in makefile.splitlines() if line.startswith(".PHONY:"))
    assert "load" in phony.split()
    assert re.search(r"^load: ## \S", makefile, re.M)
    assert (ROOT / "deploy" / "load.sh").is_file()
