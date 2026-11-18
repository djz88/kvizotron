"""Repository text stays English (CLAUDE.md, Conventions, Language).

Czech belongs only in `README.cs.md`, user-facing texts (translations and the tests that assert
them), sample content for Czech users and quoted UI copy or owner phrases.
"""

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Frequent Czech words that English text does not use, some also as typed without diacritics.
# A line is a Czech sentence with two of them, or with one and a word written with a Czech letter.
CZECH_WORDS = frozenset(
    "je že jako nebo když jsou není aby při které který která jen už také než protože podle mezi "
    "pokud tak bude musí může jsem jeho její tento tato toto tady kde se na ze pro "
    "ktere ktery ktera kdyz neni protoze musi muze".split()
)
# The app name is spelled with a Czech letter in English text too.
APP_NAME = "kvízotron"
# Docstring quotes open text, not a quotation.
DOCSTRING_QUOTES = re.compile(r"\"\"\"|'''")
# Quoted text and inline code cite UI copy, test data or owner phrases and may stay Czech.
QUOTED = re.compile(r"`[^`\n]*`|\"[^\"\n]*\"|„[^“\n]*“|“[^”\n]*”|«[^»\n]*»")
WORD = re.compile(r"[^\W\d_]+")
CZECH_LETTER = re.compile(r"[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]")
# Copy tables in plans give the Czech text in a column named after the language.
TRANSLATION_COLUMNS = {"cs", "uk"}

# Czech by purpose: user-facing texts, their tests and sample content for Czech users.
# The logo artwork carries its Czech title and description as drawn.
CZECH_BY_PURPOSE = (
    "tests/",
    "README.cs.md",
    "app/providers/csv_io/sample/",
    "app/api/assets/logo-",
)
NOT_TEXT = (
    ".po",
    ".mo",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".zip",
)
VENDORED = (".min.js", ".min.css")

# Build, deploy and tool files speak to developers: no Czech letter at all, strings included.
TOOLING = ("Makefile", "Dockerfile", ".dockerignore", ".gitignore", ".pre-commit-config.yaml")
TOOLING_DIRS = (".github/", "deploy/", "tools/", ".claude/hooks/")
# The app name, and question prompts the smoke and load tests create as a Czech admin would.
TOOLING_ALLOWED = ("Kvízotron", "Otázka", "Vyfoťte")


def _tracked() -> list[str]:
    listing = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    names = (ROOT / name for name in listing.stdout.split("\0") if name)
    return [
        str(path.relative_to(ROOT)) for path in names if path.is_file() and not path.is_symlink()
    ]


def _text(name: str) -> list[str]:
    return (ROOT / name).read_text(encoding="utf-8").splitlines()


def _prose(lines: list[str]) -> Iterator[tuple[int, str]]:
    """Lines as a reader takes them: no code blocks, no quoted text, no translation columns."""
    in_code = False
    skipped: set[int] = set()
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if line.lstrip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            names = [cell.strip().lower() for cell in cells]
            if TRANSLATION_COLUMNS.intersection(names):
                skipped = {i for i, name in enumerate(names) if name in TRANSLATION_COLUMNS}
            line = "|".join(cell for i, cell in enumerate(cells) if i not in skipped)
        else:
            skipped = set()
        yield number, QUOTED.sub(" ", DOCSTRING_QUOTES.sub(" ", line))


def czech_sentences(lines: list[str]) -> list[tuple[int, list[str]]]:
    found = []
    for number, prose in _prose(lines):
        words = WORD.findall(prose.lower())
        common = sorted({word for word in words if word in CZECH_WORDS})
        spelled = any(
            CZECH_LETTER.search(word)
            for word in words
            if word not in CZECH_WORDS and word != APP_NAME
        )
        if common and len(common) + spelled >= 2:
            found.append((number, common))
    return found


@pytest.mark.parametrize(
    "line",
    [
        "Každý fakt má jediné místo, ostatní soubory na něj odkazují.",
        "- Testy nemažeme ani neoslabujeme, aby prošly; přeskočení jen s uvedeným důvodem.",
        "# Spustí testy, které běží i v CI",
        '    """Vrátí seznam otázek, které se mají zobrazit."""',
        "# Vrati seznam otazek, ktere se maji zobrazit.",
    ],
)
def test_a_czech_sentence_is_found(line: str) -> None:
    assert czech_sentences([line])


@pytest.mark.parametrize(
    "lines",
    [
        ['The page says "Tento běh už jste v tomto prohlížeči hráli." to a returning browser.'],
        ["A run is `běh je to, co se hraje` in Czech, never kolo."],
        [
            "| Where | en | cs |",
            "|---|---|---|",
            "| note | Kept. | Pokusy, které už začaly, platí. |",
        ],
        ["```", "Testy nemažeme ani neoslabujeme, aby prošly.", "```"],
        ["Pro tip: Kvízotron runs as one process."],
    ],
)
def test_quoted_czech_and_english_are_not_czech_sentences(lines: list[str]) -> None:
    assert not czech_sentences(lines)


def test_repository_prose_is_english() -> None:
    found = []
    for name in _tracked():
        if name.startswith(CZECH_BY_PURPOSE) or name.endswith(NOT_TEXT + VENDORED):
            continue
        for number, words in czech_sentences(_text(name)):
            found.append(f"{name}:{number}: {', '.join(words)}")
    assert not found, "Czech sentences outside quotes; write them in English:\n" + "\n".join(found)


def czech_letters(lines: list[str]) -> list[int]:
    found = []
    for number, line in enumerate(lines, 1):
        for allowed in TOOLING_ALLOWED:
            line = line.replace(allowed, "")
        if CZECH_LETTER.search(line):
            found.append(number)
    return found


def test_tooling_allows_only_the_app_name_and_test_prompts() -> None:
    allowed = ['PROJECT = "Kvízotron"', "'prompt': {'cs': 'Otázka'}"]
    assert czech_letters(allowed + ["# Spustí testy", 'print("Hotovo")', "echo 'Záloha'"]) == [3, 5]


def test_build_deploy_and_tool_files_have_no_czech() -> None:
    found = []
    for name in _tracked():
        if not (name in TOOLING or name.startswith(TOOLING_DIRS)) or name.endswith(NOT_TEXT):
            continue
        found += [f"{name}:{number}" for number in czech_letters(_text(name))]
    assert not found, "Czech in build, deploy or tool files:\n" + "\n".join(found)
