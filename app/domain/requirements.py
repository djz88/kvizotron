"""Settings a question type's module cannot work without (ADR-0034, FR-46).

Declared in manifests as plain values. A module counts as selected for a quiz when its type is used
in the questions or in a draw pool. Values are read through `settings.resolve`, so a global value
counts until the quiz overrides it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django.conf import settings as django_settings
from django.utils.translation import gettext

from app.domain import banks, settings
from app.domain.models import Quiz
from app.kernel import registry
from app.kernel.registry import UnknownPort

QUESTION_TYPE = "question_type"


@dataclass(frozen=True)
class Requirement:
    module: str
    key: str
    refuse: tuple[str, ...]
    use: str
    reason: str  # a msgid in the module's own catalogue

    @property
    def text(self) -> str:
        return gettext(self.reason)  # noqa: INT001  # the module's catalogue has it

    @property
    def use_label(self) -> str:
        return str(settings.CATALOGUE[self.key].value_labels[self.use])


def _of_module(module_id: str) -> list[Requirement]:
    module = next((m for m in django_settings.KVZ_MODULES if m.id == module_id), None)
    if module is None:
        return []
    return [
        Requirement(module.id, key, tuple(item.refuse), item.use, item.reason)
        for key, item in module.settings_requirements.items()
    ]


def of_type(type_id: str) -> list[Requirement]:
    try:
        return _of_module(registry.owner_of(QUESTION_TYPE, type_id))
    except UnknownPort:
        return []


def _of_types(type_ids: Iterable[str]) -> list[Requirement]:
    found: dict[tuple[str, str], Requirement] = {}
    for type_id in sorted(set(type_ids)):
        for item in of_type(type_id):
            found[(item.module, item.key)] = item
    return list(found.values())


def _pool_types(draws: Sequence[Mapping[str, Any]], locales: Sequence[str]) -> list[str]:
    return [
        question["type"]
        for row in draws
        if banks.exists(row["bank_id"])
        for question in banks.pool(row, locales)
    ]


def of_quiz(quiz: Quiz) -> list[Requirement]:
    """Of what the editor holds: a draft, or else the published content."""
    from app.domain import authoring  # it asks this module back

    types = [question["type"] for question in authoring.editable_questions(quiz)]
    return _of_types(types + _pool_types(authoring.editable_draws(quiz), quiz.supported_locales))


def of_snapshot(snapshot: Mapping[str, Any], quiz: Quiz) -> list[Requirement]:
    """Of a stored revision, whose draw rows may already hold their pool."""
    types = [question["type"] for question in snapshot.get("questions", [])]
    draws = snapshot.get("draws", [])
    held = [question["type"] for row in draws for question in row.get("pool", [])]
    return _of_types(
        types
        + held
        + _pool_types([row for row in draws if "pool" not in row], quiz.supported_locales)
    )


def unmet(quiz: Quiz, requirements: Sequence[Requirement] | None = None) -> list[Requirement]:
    needed = of_quiz(quiz) if requirements is None else requirements
    return [item for item in needed if settings.resolve(item.key, quiz) in item.refuse]


def contradiction(
    requirements: Sequence[Requirement],
) -> tuple[Requirement, Requirement] | None:
    """Two modules, each refusing what the other one offers."""
    for number, first in enumerate(requirements):
        for second in requirements[number + 1 :]:
            if (
                first.key == second.key
                and first.use in second.refuse
                and second.use in first.refuse
            ):
                return first, second
    return None


def named(key: str, quiz: Quiz) -> Requirement | None:
    """The one to apply: this quiz's first, or any module's when adding a question of its type."""
    of_this_quiz = [item for item in of_quiz(quiz) if item.key == key]
    if of_this_quiz:
        return of_this_quiz[0]
    for module in django_settings.KVZ_MODULES:
        for item in _of_module(module.id):
            if item.key == key:
                return item
    return None


def apply(requirement: Requirement, quiz: Quiz, *, admin_id: str) -> None:
    settings.set_override(requirement.key, quiz, requirement.use, admin_id=admin_id)
