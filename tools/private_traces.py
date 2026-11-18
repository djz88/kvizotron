"""Refuses a commit or a push that carries local traces: home directories, agent scratch folders,
agent session links, and the words a developer lists in `.git/info/private-traces`.

The repository is public, so the personal words (a username, the address of a home network,
an e-mail) never go into it: they live in the untracked `.git/info/private-traces`, one per line,
`#` starts a comment. The general patterns below need no list.

A line `allow TEXT [PATH...]` in the same list is an exception, not a word: a hit that lies inside
TEXT passes, in the named files only, or everywhere without a path (commit messages take only
those). It lets the owner be named where GitHub and readers look for them, such as
`.github/CODEOWNERS` and `SECURITY.md`, while the bare word is still refused elsewhere.

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
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Allow:
    """A text that may appear in `paths` (all files when empty) although it holds a listed word."""

    text: str
    paths: tuple[str, ...] = ()

    def holds_in(self, name: str | None) -> bool:
        return not self.paths or name in self.paths


def _entries(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = (
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )
    return [line for line in lines if line]


def _is_allow(line: str) -> bool:
    return line.split()[0] == "allow"


def private_words(path: Path) -> list[str]:
    """The developer's own list; a missing file is an empty list."""
    return [line for line in _entries(path) if not _is_allow(line)]


def allowances(path: Path) -> list[Allow]:
    """The `allow TEXT [PATH...]` lines of the same list; `allow` without a text is ignored."""
    found = []
    for line in _entries(path):
        if _is_allow(line) and len(line.split()) > 1:
            text, *paths = line.split()[1:]
            found.append(Allow(text, tuple(paths)))
    return found


def allowed_in(allows: Sequence[Allow], name: str | None) -> list[str]:
    """The allowed texts for a file; `None` (a commit message) takes only those for everywhere."""
    return [allow.text for allow in allows if allow.holds_in(name)]


def pattern(words: list[str]) -> re.Pattern[str]:
    if not words:
        return GENERAL
    personal = "|".join(re.escape(word) for word in words)
    return re.compile(f"{GENERAL.pattern}|(?i:{personal})", re.MULTILINE)


def traces(text: str, found: re.Pattern[str], allowed: Sequence[str] = ()) -> list[str]:
    """A hit that lies inside an occurrence of an allowed text (any case) is not a trace."""
    spans = [
        (match.start(), match.end())
        for text_allowed in allowed
        for match in re.finditer(re.escape(text_allowed), text, re.IGNORECASE)
    ]
    return sorted(
        {
            match.group(0)
            for match in found.finditer(text)
            if not any(start <= match.start() and match.end() <= end for start, end in spans)
        }
    )


def _relative(name: str) -> str:
    """The path as the list names it: from the repository root, with `/`."""
    path = Path(name)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            return path.as_posix()
    return path.as_posix().removeprefix("./")


def check_files(
    paths: list[str], found: re.Pattern[str], allows: Sequence[Allow] = ()
) -> list[str]:
    problems = []
    for name in paths:
        path = Path(name)
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        allowed = allowed_in(allows, _relative(name))
        text = data.decode("utf-8", "ignore")
        problems += [f"{name}: {hit}" for hit in traces(text, found, allowed)]
    return problems


def check_message(path: str, found: re.Pattern[str], allows: Sequence[Allow] = ()) -> list[str]:
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return [f"commit message: {hit}" for hit in traces(body, found, allowed_in(allows, None))]


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return done.stdout


def _added_lines(commit: str) -> dict[str, list[str]]:
    """The lines a commit adds, by the file they go to.

    A file header is read only between `diff --git` and the first `@@`, so an added line that
    itself starts with "++" is not taken for one.
    """
    added: dict[str, list[str]] = {}
    name, in_hunk = "", False
    shown = _git(
        "-c", "core.quotePath=false", "show", "--format=", "--unified=0", "--no-color", commit
    )
    for line in shown.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
        elif not in_hunk and line.startswith("+++ "):
            name = line[4:].removeprefix("b/")
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            added.setdefault(name, []).append(line[1:])
    return added


def check_push(found: re.Pattern[str], allows: Sequence[Allow] = ()) -> list[str]:
    """pre-commit gives the range in PRE_COMMIT_FROM_REF and PRE_COMMIT_TO_REF."""
    start, end = os.environ.get("PRE_COMMIT_FROM_REF"), os.environ.get("PRE_COMMIT_TO_REF")
    if not end:
        return []
    span = f"{start}..{end}" if start and set(start) != {"0"} else end
    problems = []
    for commit in _git("rev-list", span).split():
        message = _git("log", "-1", "--format=%B", commit)
        hits = traces(message, found, allowed_in(allows, None))
        problems += [f"{commit[:7]} message: {hit}" for hit in hits]
        for name, lines in _added_lines(commit).items():
            hits = traces("\n".join(lines), found, allowed_in(allows, name))
            problems += [f"{commit[:7]}: {hit}" for hit in hits]
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
    found, allows = pattern(words), allowances(path)
    if mode == "files":
        problems = check_files(rest, found, allows)
    elif mode == "message":
        problems = check_message(rest[0], found, allows)
    else:
        problems = check_push(found, allows)
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
