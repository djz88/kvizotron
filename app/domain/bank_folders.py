"""Folders of a question bank: a tree of at most four levels, one folder per question (ADR-0041).

A folder is an object of its own. Draw rows and files refer to it, so renaming or moving one
never breaks them, and it is deleted only when it holds nothing.
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Count
from django.utils.translation import gettext as _

from app.contracts import QuestionTypePlugin
from app.domain.models import BankFolder, BankQuestion, QuestionBank, QuizRevision
from app.kernel import audit, registry

MAX_DEPTH = 4
MAX_NAME = 80
SEPARATOR = "/"


class FolderError(Exception):
    """Base of every refusal, so a view can show the message of whichever one it meets."""


class FolderNameInvalid(FolderError):
    pass


class FolderNameTaken(FolderError):
    pass


class FolderTooDeep(FolderError):
    pass


class FolderCycle(FolderError):
    pass


class FolderNotEmpty(FolderError):
    pass


class WrongBank(FolderError):
    pass


class FolderInUse(FolderError):
    """A draw row names the folder by id, so the folder cannot leave the bank it is in."""

    def __init__(self, quizzes: Sequence[str]) -> None:
        super().__init__(
            _("This folder is used by these quizzes: %(quizzes)s") % {"quizzes": ", ".join(quizzes)}
        )
        self.quizzes = list(quizzes)


def _audit(action: str, bank_id: Any, admin_id: str | None) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="question_bank",
        entity_id=str(bank_id),
        details={},
    )


def clean_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_NAME or SEPARATOR in name:
        raise FolderNameInvalid(
            _("A folder name has 1 to %(count)s characters and no slash.") % {"count": MAX_NAME}
        )
    return name


def _depth(folder: BankFolder | None) -> int:
    """Levels from the top down to and including this folder; 0 for no folder."""
    depth = 0
    while folder is not None:
        depth += 1
        folder = folder.parent
    return depth


def _height(folder: BankFolder) -> int:
    """Levels of the subtree, counting the folder itself."""
    height, frontier = 0, [folder.pk]
    while frontier:
        height += 1
        frontier = list(
            BankFolder.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
        )
    return height


def _taken(bank_id: Any, parent_id: Any, name: str, *, besides: Any = None) -> BankFolder | None:
    wanted = name.casefold()
    siblings = BankFolder.objects.filter(bank_id=bank_id, parent_id=parent_id)
    for sibling in siblings:
        if sibling.pk != besides and sibling.name.casefold() == wanted:
            return sibling
    return None


def _refuse_taken(bank_id: Any, parent_id: Any, name: str, *, besides: Any = None) -> None:
    if _taken(bank_id, parent_id, name, besides=besides) is not None:
        raise FolderNameTaken(_("There is a folder with this name already."))


def _check_depth(levels: int) -> None:
    if levels > MAX_DEPTH:
        raise FolderTooDeep(
            _("Folders can be at most %(count)s levels deep.") % {"count": MAX_DEPTH}
        )


def create(
    bank: QuestionBank, parent: BankFolder | None, name: str, *, admin_id: str | None
) -> BankFolder:
    name = clean_name(name)
    if parent is not None and parent.bank_id != bank.id:
        raise WrongBank(_("The folder is in another bank."))
    with transaction.atomic():
        if parent is not None:
            parent.refresh_from_db()  # the checks below must see what is stored now
        _check_depth(_depth(parent) + 1)
        _refuse_taken(bank.id, parent.pk if parent else None, name)
        folder = BankFolder.objects.create(bank=bank, parent=parent, name=name)
        _audit("bank.folder_created", bank.id, admin_id)
    return folder


def rename(folder: BankFolder, name: str, *, admin_id: str | None) -> None:
    name = clean_name(name)
    with transaction.atomic():
        _refuse_taken(folder.bank_id, folder.parent_id, name, besides=folder.pk)
        folder.name = name
        folder.save()
        _audit("bank.folder_renamed", folder.bank_id, admin_id)


def move(folder: BankFolder, parent: BankFolder | None, *, admin_id: str | None) -> None:
    if parent is not None and parent.bank_id != folder.bank_id:
        raise WrongBank(_("The folder is in another bank."))
    with transaction.atomic():
        # Transactions are IMMEDIATE, so two moves are checked one after the other, each
        # against what the other stored; checking outside would let two of them make a cycle.
        folder.refresh_from_db()
        if parent is not None:
            parent.refresh_from_db()
            if parent.pk in subtree_ids(folder):
                raise FolderCycle(
                    _("A folder cannot be moved into itself or into one of its subfolders.")
                )
        _check_depth(_depth(parent) + _height(folder))
        _refuse_taken(folder.bank_id, parent.pk if parent else None, folder.name, besides=folder.pk)
        folder.parent = parent
        folder.save()
        _audit("bank.folder_moved", folder.bank_id, admin_id)


def delete(folder: BankFolder, *, admin_id: str | None) -> None:
    with transaction.atomic():
        if folder.children.exists() or folder.questions.exists():
            raise FolderNotEmpty(_("Move or delete the questions and subfolders first."))
        bank_id = folder.bank_id
        folder.delete()
        _audit("bank.folder_deleted", bank_id, admin_id)


def delete_all(bank: QuestionBank) -> None:
    """For a bank that is going away; its questions are already gone. The audit is the bank's."""
    remaining = set(BankFolder.objects.filter(bank=bank).values_list("pk", flat=True))
    while remaining:
        parents = set(
            BankFolder.objects.filter(pk__in=remaining)
            .exclude(parent_id=None)
            .values_list("parent_id", flat=True)
        )
        leaves = remaining - parents
        BankFolder.objects.filter(pk__in=leaves).delete()
        remaining -= leaves


def path_of(folder: BankFolder | None) -> str:
    names = []
    while folder is not None:
        names.append(folder.name)
        folder = folder.parent
    return SEPARATOR.join(reversed(names))


def subtree_ids(folder: BankFolder) -> set[Any]:
    """The folder and everything below it."""
    found, frontier = {folder.pk}, [folder.pk]
    while frontier:
        frontier = list(
            BankFolder.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
        )
        found.update(frontier)
    return found


def ensure_path(bank: QuestionBank, path: str, *, admin_id: str | None) -> BankFolder:
    """Every level that does not exist is created; an existing one is found by `casefold()`."""
    names = [clean_name(part) for part in path.split(SEPARATOR)]
    with transaction.atomic():
        folder: BankFolder | None = None
        for name in names:
            found = _taken(bank.id, folder.pk if folder else None, name)
            folder = found or create(bank, folder, name, admin_id=admin_id)
    return cast(BankFolder, folder)  # split() gives at least one name


def _paths(bank: QuestionBank) -> dict[Any, str]:
    rows = {row.pk: row for row in BankFolder.objects.filter(bank=bank)}
    paths: dict[Any, str] = {}

    def build(pk: Any) -> str:
        if pk not in paths:
            row = rows[pk]
            paths[pk] = (
                f"{build(row.parent_id)}{SEPARATOR}{row.name}" if row.parent_id else row.name
            )
        return paths[pk]

    for pk in rows:
        build(pk)
    return paths


def choices(bank: QuestionBank) -> list[tuple[str, str]]:
    """`(folder id, path)` for a select, in path order."""
    ordered = sorted(_paths(bank).items(), key=lambda item: item[1].casefold())
    return [(str(pk), path) for pk, path in ordered]


@dataclass(frozen=True)
class FolderNode:
    """`total` counts the questions of the folder and of everything below it."""

    folder: BankFolder
    total: int
    subfolders: int
    children: list[FolderNode] = field(default_factory=list)


def tree(bank: QuestionBank) -> list[FolderNode]:
    """Two queries, however many folders there are. Siblings are in name order."""
    folders = sorted(BankFolder.objects.filter(bank=bank), key=lambda row: row.name.casefold())
    own = {
        row["folder_id"]: row["n"]
        for row in BankQuestion.objects.filter(bank=bank, folder__isnull=False)
        .values("folder_id")
        .annotate(n=Count("pk"))
    }
    by_parent: dict[Any, list[BankFolder]] = {}
    for row in folders:
        by_parent.setdefault(row.parent_id, []).append(row)

    def build(row: BankFolder) -> FolderNode:
        children = [build(child) for child in by_parent.get(row.pk, [])]
        total = own.get(row.pk, 0) + sum(child.total for child in children)
        return FolderNode(row, total, len(children), children)

    return [build(row) for row in by_parent.get(None, [])]


def unfiled_count(bank: QuestionBank) -> int:
    return BankQuestion.objects.filter(bank=bank, folder__isnull=True).count()


def _without_latin_marks(text: str) -> str:
    """Decided by the letter, so `й` and `ї` stay, as there they make a different letter."""
    kept: list[str] = []
    latin = False
    for char in unicodedata.normalize("NFD", text):
        if unicodedata.combining(char):
            if not latin:
                kept.append(char)
            continue
        latin = unicodedata.name(char, "").startswith("LATIN")
        kept.append(char)
    return "".join(kept)


def fold(text: str) -> str:
    return _without_latin_marks(text.casefold())


def _prompts(question: dict[str, Any]) -> list[str]:
    try:
        plugin = cast(
            QuestionTypePlugin,
            registry.get("question_type", question["type"], include_disabled=True),
        )
    except LookupError, KeyError:
        return []
    found = []
    for code, _name in django_settings.LANGUAGES:
        try:
            prompt = plugin.public_payload(question["definition"], code).get("prompt")
        except LookupError, TypeError, ValueError, AttributeError, KeyError:
            continue
        if prompt:
            found.append(str(prompt))
    return found


def search(bank: QuestionBank, text: str) -> list[BankQuestion]:
    """By the question in any language, its tags and its folder path, in the order of creation."""
    wanted = fold(text.strip())
    if not wanted:
        return []
    paths = _paths(bank)
    hits = []
    for row in BankQuestion.objects.filter(bank=bank).order_by("id"):
        parts = [*_prompts(row.question_json), *row.tags, paths.get(row.folder_id, "")]
        if any(wanted in fold(part) for part in parts):
            hits.append(row)
    return hits


def move_questions(
    bank: QuestionBank,
    question_ids: Sequence[Any],
    folder: BankFolder | None,
    *,
    admin_id: str | None,
) -> int:
    """All or nothing; `None` unfiles. Nothing outside the bank is touched."""
    if folder is not None and folder.bank_id != bank.id:
        raise WrongBank(_("The folder is in another bank."))
    with transaction.atomic():
        chosen = BankQuestion.objects.filter(bank=bank, pk__in=question_ids)
        if chosen.count() != len(set(map(str, question_ids))):
            raise WrongBank(_("A chosen question is not in this bank."))
        moved = chosen.update(folder=folder)
        _audit("bank.questions_moved", bank.id, admin_id)
    return moved


def _refuse_in_use(folder_ids: set[Any]) -> None:
    """Superseded revisions hold copies; a draft, a published and an archived one name folders."""
    wanted = {str(pk) for pk in folder_ids}
    revisions = QuizRevision.objects.filter(
        status__in=(
            QuizRevision.Status.DRAFT,
            QuizRevision.Status.PUBLISHED,
            QuizRevision.Status.ARCHIVED,
        )
    ).select_related("quiz")
    quizzes = sorted(
        {
            revision.quiz.slug
            for revision in revisions
            if any(
                row.get("folder_id") in wanted for row in revision.snapshot_json.get("draws", [])
            )
        }
    )
    if quizzes:
        raise FolderInUse(quizzes)


def transfer(
    folder: BankFolder, bank: QuestionBank, parent: BankFolder | None, *, admin_id: str | None
) -> None:
    """Moves a folder with everything in it to a place in any bank, or inside its own."""
    if bank.id == folder.bank_id:
        move(folder, parent, admin_id=admin_id)
        return
    if parent is not None and parent.bank_id != bank.id:
        raise WrongBank(_("The folder is in another bank."))
    with transaction.atomic():
        folder.refresh_from_db()
        if parent is not None:
            parent.refresh_from_db()
        ids = subtree_ids(folder)
        _refuse_in_use(ids)
        _check_depth(_depth(parent) + _height(folder))
        _refuse_taken(bank.id, parent.pk if parent else None, folder.name)
        source = folder.bank_id
        BankFolder.objects.filter(pk__in=ids).update(bank=bank)
        BankQuestion.objects.filter(folder_id__in=ids).update(bank=bank)
        BankFolder.objects.filter(pk=folder.pk).update(parent=parent)
        _audit("bank.folder_moved", source, admin_id)
        _audit("bank.folder_moved", bank.id, admin_id)


def promote(folder: BankFolder, *, admin_id: str | None) -> QuestionBank:
    """The folder becomes a bank named like it; its subfolders are the top of that bank."""
    with transaction.atomic():
        folder.refresh_from_db()
        ids = subtree_ids(folder)
        _refuse_in_use(ids)
        source = folder.bank_id
        new = QuestionBank.objects.create(name=folder.name, created_by=admin_id or "")
        below = ids - {folder.pk}
        BankFolder.objects.filter(pk__in=below).update(bank=new)
        BankFolder.objects.filter(parent=folder).update(parent=None)
        BankQuestion.objects.filter(folder_id__in=below).update(bank=new)
        BankQuestion.objects.filter(folder=folder).update(bank=new, folder=None)
        folder.delete()
        _audit("bank.created", new.id, admin_id)
        _audit("bank.folder_promoted", source, admin_id)
    return new
