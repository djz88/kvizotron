"""Tool for TECH_DEBT.md: check, tidy, create and resolve an item.

Usage: tech_debt.py --doc PATH {check | tidy | create TITLE | resolve ID}

The archive is TECH_DEBT_archive.md next to the document. Standard library only, no network.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import tempfile
from pathlib import Path

ARCHIVE_NAME = "TECH_DEBT_archive.md"
_SECTION = re.compile(r"^##\s+(\S.*?)\s*$")
_ITEM = re.compile(r"^###\s+\[?(TD-[A-Za-z0-9-]+)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_OPEN_FORM = re.compile(r"^### (TD-[A-Za-z0-9-]+) \S.*? — OPEN\s*$")
_RESOLVED_FORM = re.compile(
    r"^### (TD-[A-Za-z0-9-]+) \S.*? — ✅ RESOLVED \(\d{4}-\d{2}-\d{2}\)\s*$"
)
_OPEN_TAIL = re.compile(r" — OPEN(\s*)$")
_NUMBER = re.compile(r"^TD-(\d+)$")


class Failure(Exception):
    """A reason to stop with exit code 1."""


def _today() -> str:
    return datetime.date.today().isoformat()


def _repo_root() -> Path:
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return folder
    return here


def _safe(path: str, *, must_exist: bool) -> Path:
    """A document path inside the repository, never a symlink."""
    candidate = Path(path)
    if candidate.is_symlink():
        raise Failure(f"{path}: symbolic link is not followed")
    resolved = candidate.resolve()
    root = _repo_root()
    if root != resolved and root not in resolved.parents:
        raise Failure(f"{path}: path is outside the repository")
    if must_exist and not resolved.is_file():
        raise Failure(f"{path}: file does not exist")
    return resolved


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _write(path: Path, text: str) -> None:
    """The whole file or none of it: a temporary file next to it, then a rename."""
    handle, name = tempfile.mkstemp(prefix=".tech_debt.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write(text)
        if path.is_file():
            os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    except BaseException:
        if os.path.exists(name):
            os.unlink(name)
        raise


def _scan(lines: list[str]) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """([(upper-cased name, index)] of the `## ` sections, [(line, index)] of the `### ` headings)
    outside code fences."""
    sections: list[tuple[str, int]] = []
    headings: list[tuple[str, int]] = []
    fenced = False
    for index, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        section = _SECTION.match(line)
        if section:
            sections.append((section.group(1).upper(), index))
        elif line.startswith("### "):
            headings.append((line.rstrip("\r\n"), index))
    return sections, headings


def _split(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _terminated(line: str) -> str:
    return line if line.endswith("\n") else line + "\n"


def check_problems(name: str, text: str, archive_name: str, archive: str | None) -> list[str]:
    """One `file:line: problem` per breach of the layout, in the order of the lines."""
    out: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    if archive is not None:
        for line in _split(archive):
            match = _ITEM.match(line)
            if match:
                seen.add(match.group(1))
    lines = _split(text)
    sections, headings = _scan(lines)
    opens = [i for n, i in sections if n == "OPEN"]
    resolved = [i for n, i in sections if n == "RESOLVED"]
    first_open = opens[0] if opens else None
    first_resolved = resolved[0] if resolved else None
    layout = first_open is not None and first_resolved is not None
    if layout and first_open > first_resolved:
        out.append((name, first_open + 1, "OPEN section is not the last one before RESOLVED"))
    for _, index in sections:
        if layout and first_open < first_resolved and first_open < index < first_resolved:
            out.append((name, index + 1, "section between OPEN and RESOLVED"))
    starts = [i for i in (first_open, first_resolved) if i is not None]
    for heading, index in headings:
        if (
            starts
            and index > min(starts)
            and not (_OPEN_FORM.match(heading) or _RESOLVED_FORM.match(heading))
        ):
            out.append((name, index + 1, "heading is neither an OPEN nor a RESOLVED item"))
        ident = _ITEM.match(heading)
        if layout and first_open < index < first_resolved and ident and _is_resolved(heading):
            out.append((name, index + 1, f"resolved item {ident.group(1)} is in OPEN"))
    for heading, index in headings:
        ident = _ITEM.match(heading)
        if not ident:
            continue
        if ident.group(1) in seen:
            out.append((name, index + 1, f"duplicate id {ident.group(1)}"))
        seen.add(ident.group(1))
    if archive is not None:
        archive_seen: set[str] = set()
        for index, line in enumerate(_split(archive)):
            match = _ITEM.match(line)
            if match and match.group(1) in archive_seen:
                out.append((archive_name, index + 1, f"duplicate id {match.group(1)}"))
            if match:
                archive_seen.add(match.group(1))
    out.sort(key=lambda item: (item[0] != name, item[1]))
    return [f"{file}:{line}: {problem}" for file, line, problem in out]


def _open_range(lines: list[str]) -> tuple[int, int]:
    """(index of the `## OPEN` heading, index after its last line)."""
    sections, _ = _scan(lines)
    for position, (name, index) in enumerate(sections):
        if name == "OPEN":
            end = sections[position + 1][1] if position + 1 < len(sections) else len(lines)
            return index, end
    raise Failure("the document has no ## OPEN section")


def _item_ranges(lines: list[str], start: int, end: int) -> list[tuple[int, int, str]]:
    """(first line, after last line, heading) of every `### ` item of lines[start:end]."""
    _, headings = _scan(lines)
    inside = [(index, heading) for heading, index in headings if start <= index < end]
    ranges = []
    for position, (index, heading) in enumerate(inside):
        stop = inside[position + 1][0] if position + 1 < len(inside) else end
        ranges.append((index, stop, heading))
    return ranges


def _all_ids(*texts: str | None) -> list[str]:
    ids: list[str] = []
    for text in texts:
        if text is None:
            continue
        _, headings = _scan(_split(text))
        ids.extend(m.group(1) for heading, _ in headings if (m := _ITEM.match(heading)))
    return ids


def _move(text: str, archive: str | None, wanted) -> tuple[str, str, list[str]]:
    """The documents after the items for which `wanted(heading)` is true moved from OPEN to the
    top of the archive's RESOLVED, and the ids moved."""
    lines = _split(text)
    start, end = _open_range(lines)
    moving = [r for r in _item_ranges(lines, start + 1, end) if wanted(r[2])]
    if not moving:
        return text, archive or "", []
    blocks: list[list[str]] = []
    for first, stop, _ in moving:
        block = lines[first:stop]
        while block and not block[-1].strip():
            block.pop()
        blocks.append([_terminated(line) for line in block])
    kept = [
        line
        for index, line in enumerate(lines)
        if not any(first <= index < stop for first, stop, _ in moving)
    ]
    arch = (
        _split(archive)
        if archive is not None
        else _split("# Technical Debt — Archive\n\n## RESOLVED\n")
    )
    sections, _ = _scan(arch)
    heads = [index for name, index in sections if name == "RESOLVED"]
    if not heads:
        if arch:
            arch[-1] = _terminated(arch[-1])
        arch += ["\n", "## RESOLVED\n"]
        heads = [len(arch) - 1]
    at = heads[0]
    arch[at] = _terminated(arch[at])
    rest = arch[at + 1 :]
    while rest and not rest[0].strip():
        rest.pop(0)
    inserted: list[str] = ["\n"]
    for number, block in enumerate(blocks):
        inserted += block
        if number + 1 < len(blocks) or rest:
            inserted.append("\n")
    new_archive = "".join(arch[: at + 1] + inserted + rest)
    ids = [m.group(1) for _, _, heading in moving if (m := _ITEM.match(heading))]
    return "".join(kept), new_archive, ids


def _is_resolved(heading: str) -> bool:
    return "✅" in heading or "RESOLVED" in heading.upper()


def _store(main: Path, archive_path: Path, text: str, archive: str) -> None:
    # archive first: an interruption leaves a duplicate id for `check`, never a lost item
    _write(archive_path, archive)
    _write(main, text)


def _paths(doc: str, *, must_exist: bool = True) -> tuple[Path, Path]:
    main = _safe(doc, must_exist=must_exist)
    archive = _safe(str(Path(doc).with_name(ARCHIVE_NAME)), must_exist=False)
    return main, archive


def cmd_check(doc: str) -> int:
    main, archive_path = _paths(doc)
    text = _read(main) or ""
    problems = check_problems(Path(doc).name, text, ARCHIVE_NAME, _read(archive_path))
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def cmd_tidy(doc: str) -> int:
    main, archive_path = _paths(doc)
    text = _read(main) or ""
    new_text, new_archive, ids = _move(text, _read(archive_path), _is_resolved)
    if ids:
        _store(main, archive_path, new_text, new_archive)
    for ident in ids:
        print(f"moved {ident}")
    return 0


def cmd_create(doc: str, title: str) -> int:
    title = " ".join(title.split())
    if not title:
        raise Failure("item title is empty")
    main, archive_path = _paths(doc)
    text = _read(main) or ""
    numbers = [
        int(m.group(1))
        for ident in _all_ids(text, _read(archive_path))
        if (m := _NUMBER.match(ident))
    ]
    ident = f"TD-{max(numbers, default=0) + 1:03d}"
    lines = _split(text)
    start, end = _open_range(lines)
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    if last > start:
        lines[last - 1] = _terminated(lines[last - 1])
    block = ["\n", f"### {ident} {title} — OPEN\n", "- Where:\n", "- Effect:\n", "- Solution:\n"]
    tail = lines[end:]
    if tail:
        block.append("\n")
    _write(main, "".join(lines[:last] + block + tail))
    print(ident)
    return 0


def cmd_resolve(doc: str, ident: str) -> int:
    main, archive_path = _paths(doc)
    text = _read(main) or ""
    lines = _split(text)
    start, end = _open_range(lines)
    found = [
        r
        for r in _item_ranges(lines, start + 1, end)
        if (m := _ITEM.match(r[2])) and m.group(1) == ident
    ]
    if not found:
        raise Failure(f"{ident}: item does not exist in OPEN")
    first, _, heading = found[0]
    if not _is_resolved(heading):
        if not _OPEN_TAIL.search(lines[first]):
            raise Failure(f"{ident}: item heading does not end in “— OPEN”")
        lines[first] = _OPEN_TAIL.sub(f" — ✅ RESOLVED ({_today()})\\1", lines[first])
    new_text, new_archive, ids = _move(
        "".join(lines),
        _read(archive_path),
        lambda h: (m := _ITEM.match(h)) is not None and m.group(1) == ident,
    )
    _store(main, archive_path, new_text, new_archive)
    for moved in ids:
        print(f"moved {moved}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tech_debt", description=__doc__)
    parser.add_argument("--doc", required=True, help="cesta k TECH_DEBT.md")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("tidy")
    commands.add_parser("create").add_argument("title")
    commands.add_parser("resolve").add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return cmd_check(args.doc)
        if args.command == "tidy":
            return cmd_tidy(args.doc)
        if args.command == "create":
            return cmd_create(args.doc, args.title)
        return cmd_resolve(args.doc, args.id)
    except (Failure, OSError, UnicodeDecodeError) as exc:
        print(f"tech_debt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
