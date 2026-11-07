"""The make tech-debt-* targets, on a copy, plus the real document."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tech_debt.py"
DOCUMENT = """# Technical Debt

## OPEN

### TD-001 First — OPEN
- Where: x
- Effect: y
- Solution: z

## RESOLVED
"""
ARCHIVE = "# Technical Debt — Archive\n\n## RESOLVED\n"


def tool(doc: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(TOOL), "--doc", str(doc), *args]
    return subprocess.run(command, capture_output=True, text=True, cwd=doc.parent, check=False)


@pytest.fixture
def doc(tmp_path):
    (tmp_path / ".git").mkdir()
    path = tmp_path / "TECH_DEBT.md"
    path.write_text(DOCUMENT)
    (tmp_path / "TECH_DEBT_archive.md").write_text(ARCHIVE)
    return path


def test_real_document_is_valid():
    assert tool(ROOT / "docs" / "_architecture" / "TECH_DEBT.md", "check").returncode == 0


def test_create_takes_the_next_number(doc):
    assert tool(doc, "create", "Second").returncode == 0
    assert "### TD-002 Second — OPEN\n- Where:\n- Effect:\n- Solution:" in doc.read_text()


def test_resolve_moves_the_item_to_the_archive(doc):
    assert tool(doc, "resolve", "TD-001").returncode == 0
    assert "TD-001" not in doc.read_text()
    archive = (doc.parent / "TECH_DEBT_archive.md").read_text()
    assert "TD-001 First — ✅ RESOLVED" in archive and "- Effect: y" in archive


def test_tidy_moves_items_resolved_by_hand(doc):
    doc.write_text(DOCUMENT.replace("— OPEN", "— ✅ RESOLVED (2026-11-06)"))
    assert tool(doc, "tidy").returncode == 0
    assert "TD-001" in (doc.parent / "TECH_DEBT_archive.md").read_text()
    assert "TD-001" not in doc.read_text()


def test_check_refuses_a_broken_item(doc):
    doc.write_text(DOCUMENT.replace(" — OPEN", ""))
    assert tool(doc, "check").returncode != 0
