"""make plan-check: compares the files of a plan with git, in a throwaway repository."""

import subprocess
from pathlib import Path

import pytest

from tools.plan_check import main, named_files, report

PLAN = """# Plan

### Task 1

**Files:**
- Create: `app/new.py`, `app/migrations/0005_*.py`
- Modify: `app/old.py:12-30`
- Test: `tests/test_new.py`

- [ ] **Step 1: mentions `app/not_a_listed_file.py` in passing**
"""


def test_it_reads_only_the_files_blocks():
    assert named_files(PLAN) == {
        "app/new.py": "Create",
        "app/migrations/0005_*.py": "Create",
        "app/old.py": "Modify",
        "tests/test_new.py": "Test",
    }


def test_a_word_that_is_not_a_path_is_ignored():
    assert named_files("**Files:**\n- Modify: `tzdata`, `a/b.py`\n") == {"a/b.py": "Modify"}


def test_a_placeholder_number_and_a_short_path_match():
    plan = "**Files:**\n- Create: `app/m/00NN_x.py`, `admin/runs.html`\n"
    changed = {"app/m/0011_x.py", "app/api/jinja2/admin/runs.html"}
    assert report(plan, changed, set())[0] == []


def test_a_short_path_does_not_match_a_longer_name():
    assert report("**Files:**\n- Modify: `runs.html`\n", {"a/old_runs.html"}, set())[0] == [
        "runs.html"
    ]


def test_a_named_file_that_did_not_change_is_missing():
    changed = {"app/new.py", "app/migrations/0005_runs.py", "tests/test_new.py"}
    assert report(PLAN, changed, set())[0] == ["app/old.py"]


def test_a_pattern_is_satisfied_by_a_matching_file():
    changed = {"app/new.py", "app/old.py", "tests/test_new.py", "app/migrations/0005_runs.py"}
    assert report(PLAN, changed, set())[0] == []


def test_a_change_the_plan_does_not_name_is_listed_except_catalogues():
    changed = {"app/new.py", "app/other.py", "app/locale/cs/LC_MESSAGES/django.po"}
    assert report(PLAN, changed, set())[2] == ["app/other.py"]


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    run("git", "init", "-q", "-b", "main", cwd=tmp_path)
    run("git", "config", "user.email", "test@example.invalid", cwd=tmp_path)
    run("git", "config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "plan.md").write_text("**Files:**\n- Modify: `a.py`\n")
    (tmp_path / "a.py").write_text("1\n")
    run("git", "add", ".", cwd=tmp_path)
    run("git", "commit", "-qm", "start", cwd=tmp_path)
    run("git", "switch", "-qc", "work", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def check() -> int:
    return main(["--plan", "plan.md", "--base", "main"])


def test_it_fails_when_the_named_file_never_changed(repository):
    assert check() == 1


def test_it_fails_while_the_change_is_not_committed(repository, capsys):
    (repository / "a.py").write_text("2\n")
    assert check() == 1
    assert "Changed, not committed: 1" in capsys.readouterr().out


def test_it_passes_once_the_change_is_committed(repository):
    (repository / "a.py").write_text("2\n")
    run("git", "commit", "-qam", "change", cwd=repository)
    assert check() == 0


def test_a_plan_without_a_files_block_is_not_a_pass(repository):
    (repository / "empty.md").write_text("# Nothing here\n")
    assert main(["--plan", "empty.md", "--base", "main"]) == 2
