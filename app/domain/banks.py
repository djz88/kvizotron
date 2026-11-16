"""Question banks shared by all admins (FR-18). Publication copies from them; nothing links back."""

import copy
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from app.contracts import JSON, QuestionTypePlugin
from app.domain import bank_folders, questions
from app.domain.models import BankFolder, BankQuestion, QuestionBank, QuizRevision
from app.kernel import audit, registry


class BankInUse(Exception):
    def __init__(self, quizzes: Sequence[str]) -> None:
        super().__init__(", ".join(quizzes))
        self.quizzes = list(quizzes)


class NoCompleteLanguage(Exception):
    """A bank question must be usable in at least one language."""


def normal_tag(text: str) -> str:
    return text.strip().casefold()


LEVELS = ("easy", "normal", "hard")  # the tag values stay English in every language


class MoreThanOneLevel(Exception):
    """A question has one difficulty: at most one of the three level tags."""


def levels_of(tags: Sequence[str]) -> set[str]:
    """The levels a question's tags name; none means normal, decided here and never stored."""
    found = {normal_tag(tag) for tag in tags} & set(LEVELS)
    return found or {"normal"}


def check_one_level(tags: Sequence[str]) -> None:
    if len({normal_tag(tag) for tag in tags} & set(LEVELS)) > 1:
        raise MoreThanOneLevel


def level_label(level: str) -> str:
    labels = {
        "easy": pgettext("difficulty", "Easy"),
        "normal": pgettext("difficulty", "Normal"),
        "hard": pgettext("difficulty", "Hard"),
    }
    return labels.get(level, "")


def level_choices() -> list[tuple[str, str]]:
    return [("", _("Random mix")), *((level, level_label(level)) for level in LEVELS)]


def _clean_tags(tags: Sequence[str]) -> list[str]:
    seen: dict[str, str] = {}
    for tag in tags:
        if tag.strip():
            seen.setdefault(normal_tag(tag), tag.strip())
    return list(seen.values())


def _audit(action: str, bank_id: Any, admin_id: str | None) -> None:
    audit.record(
        actor_type="admin",
        actor_id=admin_id,
        action=action,
        entity_type="question_bank",
        entity_id=str(bank_id),
        details={},
    )


def create(name: str, *, admin_id: str | None) -> QuestionBank:
    with transaction.atomic():
        bank = QuestionBank.objects.create(name=name, created_by=admin_id or "")
        _audit("bank.created", bank.id, admin_id)
    return bank


def rename(bank: QuestionBank, name: str, *, admin_id: str | None) -> None:
    with transaction.atomic():
        bank.name = name
        bank.save()
        _audit("bank.renamed", bank.id, admin_id)


def used_by(bank: QuestionBank) -> list[str]:
    """Superseded revisions hold their own copies. An archived quiz can come back and publish."""
    revisions = QuizRevision.objects.filter(
        status__in=(
            QuizRevision.Status.DRAFT,
            QuizRevision.Status.PUBLISHED,
            QuizRevision.Status.ARCHIVED,
        )
    ).select_related("quiz")
    bank_id = str(bank.id)
    return sorted(
        {
            revision.quiz.slug
            for revision in revisions
            if any(row["bank_id"] == bank_id for row in revision.snapshot_json.get("draws", []))
        }
    )


def delete(bank: QuestionBank, *, admin_id: str | None) -> None:
    with transaction.atomic():
        quizzes = used_by(bank)
        if quizzes:
            raise BankInUse(quizzes)
        bank_id = bank.id
        bank.questions.all().delete()
        bank_folders.delete_all(bank)
        bank.delete()
        _audit("bank.deleted", bank_id, admin_id)


def complete_locales(question: BankQuestion, locales: Sequence[str]) -> list[str]:
    return questions.complete_locales(question.question_json, locales)


def language_counts(bank: QuestionBank, locales: Sequence[str]) -> dict[str, int]:
    """Questions complete in each language; a language with none is left out."""
    counts = dict.fromkeys(locales, 0)
    for question_json in bank.questions.values_list("question_json", flat=True):
        for code in questions.complete_locales(question_json, locales):
            counts[code] += 1
    return {code: count for code, count in counts.items() if count}


def _fresh(question_id: str, plugin: QuestionTypePlugin) -> dict[str, Any]:
    return {
        "id": question_id,
        "scoring": plugin.available_scoring_strategies()[0],
        "settings": {"points": questions.DEFAULT_POINTS},
        "sources": [],
        "explanation": {},
    }


def built_question(
    type_id: str,
    config: JSON,
    *,
    scoring: str | None = None,
    sources: Sequence[str] | None = None,
    explanation: Mapping[str, str] | None = None,
    setting_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The `question_json` a new bank question would get, without saving it."""
    plugin = cast(QuestionTypePlugin, registry.get("question_type", type_id))
    question = _fresh("", plugin)
    questions.apply_fields(
        question,
        plugin,
        config,
        scoring=scoring,
        sources=sources,
        explanation=explanation,
        setting_values=setting_values,
    )
    return question


def save_question(
    bank: QuestionBank,
    question_id: str | None,
    type_id: str,
    config: JSON,
    *,
    locales: Sequence[str],
    tags: Sequence[str],
    scoring: str | None = None,
    sources: Sequence[str] | None = None,
    explanation: Mapping[str, str] | None = None,
    new_id: str | None = None,
    admin_id: str | None = None,
    setting_values: Mapping[str, str] | None = None,
    folder: BankFolder | None | Literal["keep"] = "keep",
) -> str:
    """`new_id` makes a second save of one form update, like a quiz question."""
    plugin = cast(QuestionTypePlugin, registry.get("question_type", type_id))
    with transaction.atomic():
        row = (
            BankQuestion.objects.filter(bank=bank, pk=question_id or new_id).first()
            if question_id or new_id
            else None
        )
        if row is None:
            pk = uuid.UUID(new_id) if new_id else uuid.uuid7()
            row = BankQuestion(pk=pk, bank=bank, question_json=_fresh(str(pk), plugin))
        question = row.question_json
        questions.apply_fields(
            question,
            plugin,
            config,
            scoring=scoring,
            sources=sources,
            explanation=explanation,
            setting_values=setting_values,
        )
        if not questions.complete_locales(question, locales):
            raise NoCompleteLanguage(type_id)
        check_one_level(tags)
        row.tags = _clean_tags(tags)
        if not isinstance(folder, str):
            if folder is not None and folder.bank_id != bank.id:
                raise bank_folders.WrongBank(_("The folder is in another bank."))
            row.folder = folder
        row.save()
        _audit("bank.question_saved", bank.id, admin_id)
    return str(row.pk)


def delete_question(bank: QuestionBank, question_id: Any, *, admin_id: str | None) -> None:
    """For good: published revisions hold copies."""
    with transaction.atomic():
        bank.questions.filter(pk=question_id).delete()
        _audit("bank.question_deleted", bank.id, admin_id)


def tags_of(bank: QuestionBank) -> list[str]:
    seen: dict[str, str] = {}
    for tags in bank.questions.order_by("id").values_list("tags", flat=True):
        for tag in tags:
            seen.setdefault(normal_tag(tag), tag)
    return sorted(seen.values(), key=normal_tag)


def _matching(row: Mapping[str, Any]) -> list[BankQuestion]:
    found = BankQuestion.objects.filter(bank_id=row["bank_id"]).order_by("id")
    if row.get("folder_id"):
        folder = BankFolder.objects.filter(pk=row["folder_id"], bank_id=row["bank_id"]).first()
        if folder is None:
            return []
        found = found.filter(folder_id__in=bank_folders.subtree_ids(folder))
    return [q for q in found if matches(row, q.tags)]


def matches(row: Mapping[str, Any], tags: Sequence[str]) -> bool:
    """The tag and the difficulty of a draw row; the folder is the caller's part."""
    wanted = normal_tag(row.get("tag", ""))
    level = row.get("difficulty", "")
    return (not wanted or wanted in {normal_tag(tag) for tag in tags}) and (
        not level or level in levels_of(tags)
    )


def is_usable(question: Mapping[str, Any], locales: Sequence[str]) -> bool:
    return (
        question["type"] in registry.keys("question_type")
        and question["scoring"] in registry.keys("scoring_strategy")
        and not questions.locales_to_fix(question, locales)
        and questions.explanation_covers(question, locales)
    )


def pool(row: Mapping[str, Any], locales: Sequence[str]) -> list[dict[str, Any]]:
    """What a draw row can give in these languages, worth the row's points. Tags stay behind."""
    copied = []
    for found in _matching(row):
        if is_usable(found.question_json, locales):
            question = copy.deepcopy(found.question_json)
            question["settings"] = {**question["settings"], "points": row["points"]}
            copied.append(question)
    return copied


def usable_count(row: Mapping[str, Any], locales: Sequence[str]) -> tuple[int, int]:
    matching = _matching(row)
    usable = sum(is_usable(found.question_json, locales) for found in matching)
    return usable, len(matching)


def exists(bank_id: str) -> bool:
    return QuestionBank.objects.filter(pk=bank_id).exists()
