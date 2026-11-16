"""What the check page shows before a bank import (AC-166). It reads and never writes.

`structure` is the folder tree the planned questions will land in, with "exists" or "new" for
each folder. `short_rows` are the draw rows that would get fewer questions than they ask for once
a replace has run, counted the way the quiz editor counts them (`banks.usable_count`).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain import authoring, bank_folders, banks
from app.domain.models import BankFolder, QuestionBank, Quiz
from app.domain.question_import import ImportPlan, PlannedQuestion

SEPARATOR = bank_folders.SEPARATOR


@dataclass(frozen=True)
class PlannedFolder:
    """`count` holds the questions of the folder and of everything below it."""

    name: str
    path: str
    count: int
    exists: bool
    children: list[PlannedFolder] = field(default_factory=list)


@dataclass(frozen=True)
class Structure:
    folders: list[PlannedFolder]
    without_folder: int
    unused: list[str]


@dataclass(frozen=True)
class ShortRow:
    quiz: str
    folder: str
    tag: str
    difficulty: str
    available: int
    wanted: int


def _key(path: str) -> str:
    return path.casefold()


def _inside(path: str, folder_path: str) -> bool:
    key, folder_key = _key(path), _key(folder_path)
    return key == folder_key or key.startswith(folder_key + SEPARATOR)


def structure(plan: ImportPlan, bank: QuestionBank) -> Structure:
    existing = {_key(path) for _pk, path in bank_folders.choices(bank)}
    counts: dict[str, int] = {}
    spelling: dict[str, str] = {}
    without = 0
    for question in plan.questions:
        if not question.folder:
            without += 1
            continue
        parts = question.folder.split(SEPARATOR)
        for depth in range(1, len(parts) + 1):
            path = SEPARATOR.join(parts[:depth])
            spelling.setdefault(_key(path), path)
            counts[_key(path)] = counts.get(_key(path), 0) + 1

    def level(prefix: str) -> list[PlannedFolder]:
        found = [
            key for key in counts if key.startswith(prefix) and SEPARATOR not in key[len(prefix) :]
        ]
        nodes = []
        for key in found:
            path = spelling[key]
            nodes.append(
                PlannedFolder(
                    name=path.rsplit(SEPARATOR, 1)[-1],
                    path=path,
                    count=counts[key],
                    exists=key in existing,
                    children=level(key + SEPARATOR),
                )
            )
        return sorted(nodes, key=lambda node: node.name.casefold())

    used_tops = {key.split(SEPARATOR)[0] for key in counts}
    unused = sorted(
        (
            row.name
            for row in BankFolder.objects.filter(bank=bank, parent__isnull=True)
            if row.name.casefold() not in used_tops
        ),
        key=str.casefold,
    )
    return Structure(level(""), without, unused)


def _usable(question: PlannedQuestion, locales: Sequence[str]) -> bool:
    built = banks.built_question(
        question.type_id,
        question.config,
        scoring=question.scoring,
        sources=question.sources,
        explanation=question.explanation,
        setting_values=question.setting_values,
    )
    return banks.is_usable(built, locales)


def _available(row: dict[str, Any], quiz: Quiz, plan: ImportPlan, paths: dict[str, str]) -> int:
    folder_path = ""
    if row.get("folder_id"):
        if str(row["folder_id"]) not in paths:
            return 0
        folder_path = paths[str(row["folder_id"])]
    return sum(
        1
        for question in plan.questions
        if (not folder_path or _inside(question.folder, folder_path))
        and banks.matches(row, question.tags)
        and _usable(question, quiz.supported_locales)
    )


def short_rows(plan: ImportPlan, bank: QuestionBank) -> list[ShortRow]:
    paths = dict(bank_folders.choices(bank))
    bank_id = str(bank.id)
    short = []
    for quiz in Quiz.objects.filter(archived_at__isnull=True).order_by("slug"):
        rows = [row for row in authoring.editable_draws(quiz) if row.get("bank_id") == bank_id]
        for row in sorted(rows, key=lambda row: row.get("position", 0)):
            available = _available(row, quiz, plan, paths)
            if available < row["count"]:
                short.append(
                    ShortRow(
                        quiz=quiz.slug,
                        folder=paths.get(str(row["folder_id"]), row.get("folder_path", ""))
                        if row.get("folder_id")
                        else "",
                        tag=row.get("tag", ""),
                        difficulty=banks.level_label(row.get("difficulty", "")),
                        available=available,
                        wanted=row["count"],
                    )
                )
    return short
