"""Identifiers in the documentation stay stable and resolvable (CLAUDE.md, Documentation)."""

import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs" / "_architecture"
ADR_DIR = ARCHITECTURE / "adr"
INDEX = ARCHITECTURE / "README.md"
REFERENCE = re.compile(r"\b(FR|AC|OQ|ADR|TD)-(\d+)\b")
LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)#\s]+)")
STATUS = re.compile(r"accepted|proposed|deprecated|superseded by ADR-\d{4}")

# Criteria no test names yet. Naming says nothing about coverage: many are tested without their ID.
# The list only shrinks: a new criterion needs a test that names it.
LAST_EXCUSED = 69
AC_NOT_NAMED_BY_A_TEST = {
    "AC-19",
    "AC-20",
    "AC-21",
    "AC-22",
    "AC-23",
    "AC-24",
    "AC-25",
    "AC-26",
    "AC-27",
    "AC-28",
    "AC-29",
    "AC-30",
    "AC-31",
    "AC-33",
    "AC-34",
    "AC-35",
    "AC-36",
    "AC-37",
    "AC-39",
    "AC-41",
    "AC-43",
    "AC-44",
    "AC-48",
    "AC-50",
    "AC-53",
    "AC-54",
    "AC-62",
    "AC-63",
    "AC-64",
    "AC-65",
    "AC-66",
    "AC-67",
    "AC-68",
    "AC-69",
}


def documents() -> list[Path]:
    found = [*ARCHITECTURE.rglob("*.md"), *(ROOT / "docs").glob("*.md")]
    skills = [*ROOT.glob(".claude/skills/*/*.md"), ROOT / ".claude" / "review-profile.md"]
    return [*found, *skills, *ROOT.glob("CLAUDE.md"), *ROOT.glob("*/**/CLAUDE.md")]


def in_repository(paths: list[Path]) -> list[Path]:
    hidden = {".venv", ".worktrees", ".superpowers", ".git", ".playwright-mcp"}
    return [path for path in paths if not hidden & set(path.relative_to(ROOT).parts)]


def sources() -> list[Path]:
    return [*(ROOT / "app").rglob("*.py"), *(ROOT / "tools").rglob("*.py")]


def fr_definitions(text: str) -> list[str]:
    return re.findall(r"^\s*- (?:\*\*)?`(FR-\d+)`", text, re.M)


def table_ids(prefix: str, text: str) -> list[str]:
    return re.findall(rf"^\| ({prefix}-\d+) \|", text, re.M)


def adr_files() -> dict[str, Path]:
    return {
        f"ADR-{path.name[:4]}": path
        for path in ADR_DIR.glob("[0-9]*.md")
        if path.name[:4] != "0000"
    }


def adr_status(text: str) -> str:
    match = re.search(r"^status: (.*)$", text, re.M)
    return match[1].strip() if match else ""


def fr_index(text: str) -> dict[str, str]:
    """FR-xx -> file, read from the rows of the requirement index."""
    index = {}
    for cell, target in re.findall(r"^\| (FR-[^|]+) \| \[[^\]]+\]\(([^)]+)\) \|$", text, re.M):
        for part in cell.split(","):
            numbers = [int(number) for number in re.findall(r"FR-(\d+)", part)]
            for number in range(numbers[0], numbers[-1] + 1):
                index[f"FR-{number:02d}"] = target
    return index


def known_ids() -> set[str]:
    known = set(adr_files())
    for text in (path.read_text() for path in in_repository(documents())):
        known |= set(fr_definitions(text))
    known |= set(table_ids("AC", (ARCHITECTURE / "acceptance-criteria.md").read_text()))
    known |= set(table_ids("OQ", (ARCHITECTURE / "open-questions.md").read_text()))
    debt = (ARCHITECTURE / "TECH_DEBT.md").read_text() + (
        ARCHITECTURE / "TECH_DEBT_archive.md"
    ).read_text()
    known |= set(re.findall(r"^#+ (TD-\d+)", debt, re.M))
    return known


def duplicates(ids: list[str]) -> list[str]:
    return [item for item, count in Counter(ids).items() if count > 1]


def test_the_readers_see_real_documents():
    assert len(in_repository(documents())) > 40
    assert {"FR-01", "AC-69", "OQ-14", "ADR-0048", "TD-022"} <= known_ids()


def test_the_readers_notice_a_duplicate_and_an_unknown_reference():
    assert duplicates(fr_definitions("- `FR-01` a\n- **`FR-01`** b\n- `FR-02` c\n")) == ["FR-01"]
    assert duplicates(table_ids("AC", "| AC-01 | a |\n| AC-01 | b |\n")) == ["AC-01"]
    assert REFERENCE.search("see ADR-9999")[0] not in known_ids()
    assert fr_index("| FR-01 – FR-03, FR-07 | [a](a.md) |\n") == {
        "FR-01": "a.md",
        "FR-02": "a.md",
        "FR-03": "a.md",
        "FR-07": "a.md",
    }


def named_by_tests() -> set[str]:
    """Every AC-nn that a test file mentions, in a docstring, a name or a comment."""
    found: set[str] = set()
    for path in (ROOT / "tests").rglob("*.py"):
        if path != Path(__file__).resolve():
            found |= set(re.findall(r"\bAC-\d+\b", path.read_text()))
    return found


def test_the_readers_find_the_criteria_that_tests_name():
    assert {"AC-01", "AC-15", "AC-72"} <= named_by_tests()


def test_an_excused_criterion_is_one_no_test_names_yet():
    named = AC_NOT_NAMED_BY_A_TEST & named_by_tests()
    assert not named, f"remove from AC_NOT_NAMED_BY_A_TEST: {sorted(named)}"


def test_every_other_criterion_is_named_by_a_test():
    criteria = set(table_ids("AC", (ARCHITECTURE / "acceptance-criteria.md").read_text()))
    assert AC_NOT_NAMED_BY_A_TEST <= criteria
    assert all(int(item.split("-")[1]) <= LAST_EXCUSED for item in AC_NOT_NAMED_BY_A_TEST)
    unnamed = criteria - AC_NOT_NAMED_BY_A_TEST - named_by_tests()
    assert not unnamed, f"a test must name: {sorted(unnamed)}"


def test_each_requirement_is_defined_once():
    ids = [fr for path in in_repository(documents()) for fr in fr_definitions(path.read_text())]
    assert not duplicates(ids)


def test_each_requirement_is_defined_in_the_file_of_the_index():
    index = fr_index(INDEX.read_text())
    defined = {
        fr: path for path in in_repository(documents()) for fr in fr_definitions(path.read_text())
    }
    assert set(index) == set(defined)
    wrong = {
        fr: str(path.relative_to(ROOT))
        for fr, path in defined.items()
        if (ARCHITECTURE / index[fr]).resolve() != path.resolve()
    }
    assert not wrong


@pytest.mark.parametrize(
    ("prefix", "name"), [("AC", "acceptance-criteria.md"), ("OQ", "open-questions.md")]
)
def test_table_ids_are_unique(prefix, name):
    assert not duplicates(table_ids(prefix, (ARCHITECTURE / name).read_text()))


def test_the_index_states_the_real_range_of_ids():
    text = INDEX.read_text()
    known = known_ids()
    for prefix in ("FR", "AC"):
        last = max(int(item.split("-")[1]) for item in known if item.startswith(prefix))
        assert f"`{prefix}-01`…`{prefix}-{last:02d}`" in text, prefix


def test_every_reference_points_to_an_existing_id():
    known = known_ids()
    dangling = {
        f"{path.relative_to(ROOT)}: {match[0]}"
        for path in [*in_repository(documents()), *sources()]
        for match in REFERENCE.finditer(path.read_text())
        if match[0] not in known
    }
    assert not dangling


def test_every_relative_link_leads_to_a_file():
    broken = {
        f"{path.relative_to(ROOT)}: {target}"
        for path in in_repository(documents())
        for target in LINK.findall(path.read_text())
        if not (path.parent / target).exists()
    }
    assert not broken


@pytest.mark.parametrize("adr", sorted(adr_files()))
def test_a_decision_is_well_formed(adr):
    text = adr_files()[adr].read_text()
    assert re.search(rf"^# {adr}:", text, re.M)
    assert STATUS.fullmatch(adr_status(text))


def test_the_list_of_decisions_matches_the_decisions():
    listed = dict(
        re.findall(
            r"^\| \[(ADR-\d{4})\]\([^)]+\) \| .* \| ([^|]+?) \|$",
            (ADR_DIR / "README.md").read_text(),
            re.M,
        )
    )
    actual = {adr: adr_status(path.read_text()) for adr, path in adr_files().items()}
    assert listed == actual


def test_debt_items_are_only_under_open_and_resolved():
    text = (ARCHITECTURE / "TECH_DEBT.md").read_text()
    before_open = text[: text.index("\n## OPEN\n")]
    assert not re.findall(r"^#+ TD-\d+", before_open, re.M)
    assert "### TD-" not in before_open.replace("`### TD-NNN", "")


def agent_documents() -> list[Path]:
    return [*sorted(ROOT.glob(".claude/skills/*/*.md")), ROOT / ".claude" / "review-profile.md"]


@pytest.mark.parametrize("document", agent_documents(), ids=lambda p: p.parent.name + "/" + p.name)
def test_an_agent_document_names_only_paths_that_exist(document):
    named = re.findall(
        r"`((?:app|docs|tests|tools|deploy|\.claude)/[^`\s]+)`", document.read_text()
    )
    named += re.findall(r"\b(tests/[\w/]+\.py)\b", document.read_text())
    assert named
    assert not [path for path in named if not (ROOT / path).exists()]


@pytest.mark.parametrize(
    "skill", sorted(ROOT.glob(".claude/skills/*/SKILL.md")), ids=lambda p: p.parent.name
)
def test_a_skill_of_this_repository_is_named_after_it(skill):
    name = re.search(r"^name: (.+)$", skill.read_text(), re.M)[1]
    assert name.startswith("kvizotron-")
    assert skill.parent.name == name


# Machine traces: a home directory, an agent's scratch folder or a link to an agent session.
LOCAL_TRACES = re.compile(r"/home/[\w.-]+|/Users/[\w.-]+|/tmp/claude-\d+|claude\.ai/code/session_")


def test_documents_hold_no_local_paths_or_session_links():
    """Documents and agent files are public: no home directories, scratch folders or sessions."""
    texts = [*ROOT.glob("docs/**/*.md"), *ROOT.glob(".claude/**/*"), *ROOT.glob("**/CLAUDE.md")]
    found = [
        f"{path.relative_to(ROOT)}: {match.group(0)}"
        for path in texts
        if path.is_file() and ".venv" not in path.parts and ".worktrees" not in path.parts
        for match in LOCAL_TRACES.finditer(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not found
