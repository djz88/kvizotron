"""`make plan-check`: did every file a plan names change on this branch?

Compares the `**Files:**` blocks of a plan with git. Standard library only. It does not judge the
changes: a file that changed can still be wrong, and that is what tests and review are for.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

FILE_LINE = re.compile(r"^- (Create|Modify|Test|Delete):\s*(.*)$")
NAME = re.compile(r"`([^`]+)`")
LINES_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
GENERATED = (".mo", ".po")


def named_files(plan: str) -> dict[str, str]:
    """File -> what the plan does to it. Patterns such as `0005_*.py` stay as patterns."""
    files: dict[str, str] = {}
    in_block = False
    for line in plan.splitlines():
        if line.strip() == "**Files:**":
            in_block = True
            continue
        match = FILE_LINE.match(line)
        if in_block and match:
            for name in NAME.findall(match[2]):
                # A word without a slash or an extension is not a path (`tzdata`, `strftime`).
                if "/" in name or "." in name:
                    files[LINES_SUFFIX.sub("", name)] = match[1]
        elif in_block and line.strip():
            in_block = False
    return files


def git(*args: str, cwd: Path) -> list[str]:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return [line for line in done.stdout.splitlines() if line]


def changed_files(base: str, head: str, cwd: Path) -> set[str]:
    return set(git("diff", "--name-only", f"{base}...{head}", cwd=cwd))


def uncommitted(cwd: Path) -> set[str]:
    tracked = git("diff", "--name-only", "HEAD", cwd=cwd)
    return {*tracked, *git("ls-files", "--others", "--exclude-standard", cwd=cwd)}


def is_changed(name: str, changed: set[str]) -> bool:
    if name.endswith("/"):
        return any(path.startswith(name) for path in changed)
    # `00NN_x.py` stands for a number the plan could not know. A path may start below the top
    # folder, because a plan can say `admin/runs.html`.
    pattern = re.escape(name).replace(r"\*", "[^/]*").replace(r"\?", "[^/]").replace("NN", r"\d\d")
    return any(re.fullmatch(f"(?:.*/)?{pattern}", path) for path in changed)


def report(
    plan: str, changed: set[str], waiting: set[str]
) -> tuple[list[str], list[str], list[str]]:
    """What the plan names and did not happen; what is not committed; what the plan never named."""
    files = named_files(plan)
    missing = sorted(name for name in files if not is_changed(name, changed | waiting))
    outside = sorted(
        path
        for path in changed | waiting
        if not path.endswith(GENERATED) and not any(is_changed(name, {path}) for name in files)
    )
    return missing, sorted(waiting), outside


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    cwd = Path.cwd()
    plan = args.plan.read_text()
    if not named_files(plan):
        print(f"{args.plan}: no **Files:** block found, nothing was checked")
        return 2
    changed = changed_files(args.base, args.head, cwd)
    waiting = uncommitted(cwd) if args.head == "HEAD" else set()
    missing, not_committed, outside = report(plan, changed, waiting)
    for title, names in (
        ("Plan names it, it did not change", missing),
        ("Changed, not committed", not_committed),
        ("Changed, the plan does not name it (say why, it is not an error)", outside),
    ):
        print(f"{title}: {len(names)}")
        for name in names:
            print(f"  {name}")
    return 1 if missing or not_committed else 0


if __name__ == "__main__":
    sys.exit(main())
