"""Refuses a commit or a push that carries local traces: home directories, agent scratch folders,
agent session links, and the words a developer lists in `.git/info/private-traces`.

The repository is public, so the personal words (a username, the address of a home network,
an e-mail) never go into it: they live in the untracked `.git/info/private-traces`, one per line,
`#` starts a comment. The general patterns below need no list.

    python3 tools/private_traces.py files PATH...      # pre-commit: the staged files
    python3 tools/private_traces.py message FILE       # commit-msg: the message being written
    python3 tools/private_traces.py push               # pre-push: commits and files not yet pushed
    python3 tools/private_traces.py list               # make hooks, make doctor: is the list there?

Without the list the hooks still check the general patterns and remind you: `make private-traces`
creates an empty one. Worktrees share the list of the main checkout.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

GENERAL = re.compile(
    r"/home/[\w.-]+|/Users/[\w.-]+|/tmp/claude-\d+|claude\.ai/code/session_|^Claude-Session:",
    re.MULTILINE,
)
MISSING = (
    "private-traces: {path} is missing, so the personal words are not checked;"
    " create it with `make private-traces` (an empty one will do)"
)


def list_path(root: Path) -> Path:
    """`.git/info/private-traces` of the main checkout, also from a worktree."""
    done = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
    )
    common = Path(done.stdout.strip()) if done.returncode == 0 else root / ".git"
    return common / "info" / "private-traces"


def private_words(path: Path) -> list[str]:
    """The developer's own list; a missing file is an empty list."""
    if not path.is_file():
        return []
    lines = (
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )
    return [line for line in lines if line]


def pattern(words: list[str]) -> re.Pattern[str]:
    if not words:
        return GENERAL
    personal = "|".join(re.escape(word) for word in words)
    return re.compile(f"{GENERAL.pattern}|(?i:{personal})", re.MULTILINE)


def traces(text: str, found: re.Pattern[str]) -> list[str]:
    return sorted({match.group(0) for match in found.finditer(text)})


def check_files(paths: list[str], found: re.Pattern[str]) -> list[str]:
    problems = []
    for name in paths:
        path = Path(name)
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        problems += [f"{name}: {hit}" for hit in traces(data.decode("utf-8", "ignore"), found)]
    return problems


def check_message(path: str, found: re.Pattern[str]) -> list[str]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return [f"commit message: {hit}" for hit in traces(body, found)]


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return done.stdout


def check_push(found: re.Pattern[str]) -> list[str]:
    """pre-commit gives the range in PRE_COMMIT_FROM_REF and PRE_COMMIT_TO_REF."""
    start, end = os.environ.get("PRE_COMMIT_FROM_REF"), os.environ.get("PRE_COMMIT_TO_REF")
    if not end:
        return []
    span = f"{start}..{end}" if start and set(start) != {"0"} else end
    problems = []
    for commit in _git("rev-list", span).split():
        message = _git("log", "-1", "--format=%B", commit)
        problems += [f"{commit[:7]} message: {hit}" for hit in traces(message, found)]
        added = "\n".join(
            line[1:]
            for line in _git("show", "--format=", "--unified=0", "--no-color", commit).splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        problems += [f"{commit[:7]}: {hit}" for hit in traces(added, found)]
    return problems


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"files", "message", "push", "list"}:
        print(__doc__, file=sys.stderr)
        return 2
    path = list_path(Path.cwd())
    words = private_words(path)
    mode, rest = argv[0], argv[1:]
    if mode == "list":
        if not path.is_file():
            print(MISSING.format(path=path), file=sys.stderr)
            return 1
        print(f"private-traces: ok ({len(words)} words)")
        return 0
    if not path.is_file():
        print(MISSING.format(path=path), file=sys.stderr)
    found = pattern(words)
    if mode == "files":
        problems = check_files(rest, found)
    elif mode == "message":
        problems = check_message(rest[0], found)
    else:
        problems = check_push(found)
    for problem in problems:
        print(f"Local trace: {problem}", file=sys.stderr)
    if problems:
        print(
            "Replace it with <repo>, <scratchpad> or an example address (CLAUDE.md, Pravidla).",
            file=sys.stderr,
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
