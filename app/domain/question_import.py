"""What the rows of an import file mean (ADR-0045). The provider reads files, this reads rows.

`interpret` stores nothing, so the check step and the confirm step run the same code. The API
resolves images between `interpret` and `apply`, because that takes a provider.
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.core.validators import slug_re
from django.db import transaction
from django.utils.text import slugify
from django.utils.translation import gettext as _

from app.contracts import CsvRowError, ImageAddressInvalid, ParsedFile, QuestionTypePlugin
from app.domain import authoring, bank_folders, banks, questions, settings
from app.domain.models import BankFolder, QuestionBank, Quiz
from app.kernel import audit, registry

SCHEMA_VERSION = "1"
QUIZ_ROW = "quiz"
QUESTION_ROW = "question"
SETTING_PREFIX = "setting_"
ADDRESS = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
PLAIN_COLUMNS = (
    "schema_version",
    "row_type",
    "type",
    "points",
    "scoring",
    "sources",
    "tags",
    "folder",
    "slug",
    "locales",
    "default_locale",
)
PER_LANGUAGE = ("explanation", "title", "description")


@dataclass(frozen=True)
class Issue:
    row: int | None
    column: str | None
    message: str
    is_error: bool


@dataclass
class PlannedQuestion:
    row: int
    type_id: str
    config: dict[str, Any]
    points: int | None
    scoring: str | None
    sources: list[str]
    explanation: dict[str, str]
    setting_values: dict[str, str]
    tags: list[str]
    folder: str = ""


@dataclass
class PlannedQuiz:
    row: int
    slug: str
    locales: list[str]
    default_locale: str
    title: dict[str, str]
    description: dict[str, str]
    setting_values: dict[str, str]


@dataclass
class ImportPlan:
    quiz: PlannedQuiz | None = None
    questions: list[PlannedQuestion] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    unused_columns: list[str] = field(default_factory=list)
    refused: str | None = None


@dataclass(frozen=True)
class Target:
    kind: str  # new_quiz, draft or bank
    quiz: Quiz | None
    bank: QuestionBank | None
    replace: bool = False  # a bank: the file's questions take the place of the bank's own


@dataclass(frozen=True)
class Outcome:
    quiz: Quiz | None
    bank: QuestionBank | None
    added: int
    issues: list[Issue]
    removed: int = 0


class ReplaceRefused(Exception):
    """A replace that could not save every row: nothing was changed."""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("replace refused")
        self.issues = issues


@dataclass(frozen=True)
class Placement:
    """Where a bank import puts the file's folders. Keys are the file's top folders, casefolded."""

    under: BankFolder | None = None
    added: str = ""
    names: Mapping[str, str] = field(default_factory=dict)
    dropped: frozenset[str] = frozenset()


class PlacementInvalid(Exception):
    pass


class _RowProblem(Exception):
    def __init__(self, column: str | None, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


def languages() -> list[str]:
    return [code for code, _name in django_settings.LANGUAGES]


def _plugin(type_id: str) -> QuestionTypePlugin:
    return cast(QuestionTypePlugin, registry.get("question_type", type_id))


def known_columns() -> set[str]:
    codes = languages()
    known = set(PLAIN_COLUMNS)
    known |= {f"{name}_{code}" for name in PER_LANGUAGE for code in codes}
    known |= {f"{SETTING_PREFIX}{key}" for key in settings.CATALOGUE}
    for type_id in registry.keys("question_type"):
        known |= set(_plugin(type_id).csv_columns(codes))
    return known


def unknown_columns(columns: Iterable[str]) -> list[str]:
    known = known_columns()
    return [column for column in columns if column not in known]


def _mapped(cells: Mapping[str, str], mapping: Mapping[str, str]) -> dict[str, str]:
    """Only what the admin chose to use, under the name it stands for."""
    known = known_columns()
    result: dict[str, str] = {}
    for column, value in cells.items():
        name = mapping.get(column, column)
        if name in known:
            result[name] = value
    return result


def is_address(cell: str) -> bool:
    """Decides by the form of the cell alone, so an address never reaches a ZIP lookup."""
    return ADDRESS.match(cell) is not None


def _texts(cells: Mapping[str, str], name: str, locales: Sequence[str]) -> dict[str, str]:
    found = {locale: cells.get(f"{name}_{locale}", "").strip() for locale in locales}
    return {locale: text for locale, text in found.items() if text}


def _setting_values(
    cells: Mapping[str, str], scope: str, allowed: Iterable[str] | None = None
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Scopes come from the catalogue, so a new setting works here without a change."""
    offered = set(settings.keys_for(scope))
    if allowed is not None:
        offered &= set(allowed)
    values: dict[str, str] = {}
    problems: list[tuple[str, str]] = []
    for column, value in cells.items():
        key = column.removeprefix(SETTING_PREFIX)
        cleaned = value.strip()
        if not column.startswith(SETTING_PREFIX) or not cleaned:
            continue
        if key not in offered:
            problems.append((column, _("This setting cannot be set here.")))
        elif cleaned not in settings.CATALOGUE[key].choices:
            problems.append((column, _("This value is not offered for this setting.")))
        else:
            values[key] = cleaned
    return values, problems


def _points(cells: Mapping[str, str]) -> int | None:
    cell = cells.get("points", "").strip()
    if not cell:
        return None
    if not cell.isascii() or not cell.isdigit() or int(cell) < 1:
        raise _RowProblem("points", _("Points must be a positive whole number."))
    return int(cell)


def _sources(cells: Mapping[str, str]) -> list[str]:
    lines = [line.strip() for line in cells.get("sources", "").splitlines() if line.strip()]
    if len(lines) > questions.MAX_SOURCES:
        message = _("At most %(count)s sources are allowed.") % {"count": questions.MAX_SOURCES}
        raise _RowProblem("sources", message)
    if any(len(line) > questions.MAX_SOURCE_LENGTH for line in lines):
        limit = questions.MAX_SOURCE_LENGTH
        message = _("A source can have at most %(count)s characters.") % {"count": limit}
        raise _RowProblem("sources", message)
    return lines


def _image_column(cells: Mapping[str, str], cell: str) -> str | None:
    return next((name for name, value in cells.items() if value.strip() == cell), None)


def _check_images(
    config: Mapping[str, Any],
    cells: Mapping[str, str],
    files: frozenset[str],
    check_address: Callable[[str], None] | None,
) -> None:
    for image in questions.images_of(config):
        cell = str(image.get("source") or "")
        column = _image_column(cells, cell)
        if check_address is None:
            raise _RowProblem(column, _("Images cannot be stored on this installation."))
        if is_address(cell):
            try:
                check_address(cell)
            except ImageAddressInvalid as error:
                raise _RowProblem(column, str(error)) from error
        elif cell not in files:
            raise _RowProblem(column, _("The file %(name)s is not in the upload.") % {"name": cell})


def _question(
    number: int,
    cells: Mapping[str, str],
    locales: Sequence[str],
    files: frozenset[str],
    check_address: Callable[[str], None] | None,
) -> PlannedQuestion:
    type_id = cells.get("type", "").strip()
    try:
        plugin = _plugin(type_id)
    except LookupError as exc:
        raise _RowProblem("type", _("This question type is not known.")) from exc
    scoring = cells.get("scoring", "").strip() or None
    if scoring is not None and scoring not in plugin.available_scoring_strategies():
        raise _RowProblem("scoring", _("This scoring is not offered for this question type."))
    points = _points(cells)
    try:
        config = dict(plugin.from_csv(cells, locales))
    except CsvRowError as error:
        raise _RowProblem(error.column, str(error)) from error
    _check_images(config, cells, files, check_address)
    allowed = {*plugin.question_settings(), *settings.ALL_TYPES_QUESTION_SETTINGS}
    values, problems = _setting_values(cells, "question", allowed)
    if problems:
        raise _RowProblem(*problems[0])
    tags = [tag.strip() for tag in cells.get("tags", "").split(",") if tag.strip()]
    try:
        banks.check_one_level(tags)
    except banks.MoreThanOneLevel as exc:
        raise _RowProblem(
            "tags", _("A question can have only one of the tags easy, normal and hard.")
        ) from exc
    return PlannedQuestion(
        row=number,
        type_id=type_id,
        config=config,
        points=points,
        scoring=scoring,
        sources=_sources(cells),
        explanation=_texts(cells, "explanation", locales),
        setting_values=values,
        tags=tags,
        folder=cells.get("folder", "").strip(),
    )


def _gaps(question: PlannedQuestion, locales: Sequence[str]) -> list[Issue]:
    """A draft may be incomplete, and the publication check names the same things."""
    plugin = _plugin(question.type_id)
    found = []
    for locale in locales:
        try:
            plugin.validate_definition(question.config, locale)
        except ValueError as error:
            message = _("Language %(locale)s: %(detail)s") % {"locale": locale, "detail": error}
            found.append(Issue(question.row, None, message, False))
    return found


def _blank_correct(
    question: PlannedQuestion, cells: Mapping[str, str], locales: Sequence[str]
) -> list[Issue]:
    """Valid, as a question may have no correct answer, but usually the file forgot it."""
    if "correct" not in _plugin(question.type_id).csv_columns(locales):
        return []
    if cells.get("correct", "").strip():
        return []
    return [Issue(question.row, "correct", _("No answer is marked as correct."), False)]


def _quiz_row(number: int, cells: Mapping[str, str], plan: ImportPlan) -> PlannedQuiz | None:
    codes = languages()
    title = _texts(cells, "title", codes)
    if not title:
        plan.refused = _("The quiz row needs a title.")
        return None
    listed = [code.strip() for code in cells.get("locales", "").split(",") if code.strip()]
    locales = [code for code in codes if code in listed] if listed else list(title)
    if set(listed) - set(codes):
        plan.refused = _("The quiz row lists a language this application does not have.")
        return None
    default = cells.get("default_locale", "").strip() or locales[0]
    if default not in locales:
        plan.refused = _("The default language must be among the listed ones.")
        return None
    values, problems = _setting_values(cells, "quiz")
    plan.issues += [Issue(number, column, message, True) for column, message in problems]
    return PlannedQuiz(
        row=number,
        slug=cells.get("slug", "").strip(),
        locales=locales,
        default_locale=default,
        title=title,
        description=_texts(cells, "description", codes),
        setting_values=values,
    )


def _target_locales(target: Target, plan: ImportPlan) -> list[str]:
    if target.kind == "new_quiz":
        return plan.quiz.locales if plan.quiz else []
    if target.kind == "draft" and target.quiz is not None:
        return list(target.quiz.supported_locales)
    return languages()


def _unused(
    parsed: ParsedFile, mapping: Mapping[str, str], target: Target, rows: Sequence[Mapping]
) -> list[str]:
    known = known_columns()
    unused = [column for column in parsed.columns if mapping.get(column, column) not in known]

    def has_value(column: str) -> bool:
        return any(row.get(column, "").strip() for row in rows)

    if target.kind != "bank" and has_value("tags"):
        unused.append("tags")
    if target.kind != "bank" and has_value("folder"):
        unused.append("folder")
    if target.kind == "bank" and has_value("points"):
        unused.append("points")
    return unused


def _dropped_languages(rows: Sequence[Mapping[str, str]], locales: Sequence[str]) -> list[Issue]:
    issues = []
    for code in set(languages()) - set(locales):
        columns = {
            name
            for row in rows
            if row.get("row_type", "").strip() != QUIZ_ROW
            for name, value in row.items()
            if name.endswith(f"_{code}") and value.strip()
        }
        if columns:
            message = _("Text in language %(locale)s was left out: the target does not use it.")
            issues.append(Issue(None, None, message % {"locale": code}, False))
    return sorted(issues, key=lambda issue: issue.message)


def _folder_cell(cells: Mapping[str, str]) -> str:
    return cells.get("folder", "").strip()


def top_folders(parsed: ParsedFile, mapping: Mapping[str, str]) -> list[str]:
    """The first level of the folder paths of the question rows, first spelling kept."""
    seen: dict[str, str] = {}
    for row in parsed.rows:
        cells = _mapped(row.cells, mapping)
        if cells.get("row_type", "").strip() == QUIZ_ROW:
            continue
        top = _folder_cell(cells).split(bank_folders.SEPARATOR)[0].strip()
        if top:
            seen.setdefault(top.casefold(), top)
    return sorted(seen.values(), key=str.casefold)


def _checked_name(value: str) -> str:
    try:
        return bank_folders.clean_name(value)
    except bank_folders.FolderError as error:
        raise PlacementInvalid(str(error)) from error


def placement_of(bank: QuestionBank, values: Mapping[str, str], tops: Sequence[str]) -> Placement:
    """Form values `under`, `added`, `name_<i>` and `drop_<i>`; `i` indexes `tops`."""
    under = None
    if values.get("under", "").strip():
        try:
            under = BankFolder.objects.filter(bank=bank, pk=values["under"].strip()).first()
        except ValidationError:
            under = None
        if under is None:
            raise PlacementInvalid(_("The chosen folder is not a folder of this bank."))
    added = values.get("added", "").strip()
    names: dict[str, str] = {}
    dropped: set[str] = set()
    for index, top in enumerate(tops):
        name = values.get(f"name_{index}", "").strip()
        if name and name != top:
            names[top.casefold()] = _checked_name(name)
        if values.get(f"drop_{index}") == "1":
            dropped.add(top.casefold())
    return Placement(under, _checked_name(added) if added else "", names, frozenset(dropped))


def place(path: str, placement: Placement, under_path: str) -> str:
    """The path below the bank's top level that a file path gets."""
    parts = [part.strip() for part in path.split(bank_folders.SEPARATOR)] if path else []
    if parts:
        key = parts[0].casefold()
        if key in placement.dropped:
            parts = parts[1:]
        else:
            parts[0] = placement.names.get(key, parts[0])
    prefix = [part for part in (under_path, placement.added) if part]
    return bank_folders.SEPARATOR.join([*prefix, *parts])  # an empty part stays, to be refused


def _placed(plan: ImportPlan, placement: Placement) -> None:
    under_path = bank_folders.path_of(placement.under) if placement.under else ""
    kept = []
    for question in plan.questions:
        question.folder = place(question.folder, placement, under_path)
        names = question.folder.split(bank_folders.SEPARATOR) if question.folder else []
        try:
            for name in names:
                bank_folders.clean_name(name)
        except bank_folders.FolderError as error:
            plan.issues.append(Issue(question.row, "folder", str(error), True))
            continue
        if len(names) > bank_folders.MAX_DEPTH:
            message = _("The folder %(path)s would be deeper than %(count)s levels.")
            plan.issues.append(
                Issue(
                    question.row,
                    "folder",
                    message % {"path": question.folder, "count": bank_folders.MAX_DEPTH},
                    True,
                )
            )
        else:
            kept.append(question)
    plan.questions = kept


def interpret(
    parsed: ParsedFile,
    target: Target,
    mapping: Mapping[str, str],
    check_address: Callable[[str], None] | None,
    *,
    placement: Placement | None = None,
) -> ImportPlan:
    plan = ImportPlan()
    rows = [(row, _mapped(row.cells, mapping)) for row in parsed.rows]
    versions = {cells.get("schema_version", "").strip() for _row, cells in rows} - {""}
    if versions - {SCHEMA_VERSION}:
        plan.refused = _("This file uses a format version this application does not know.")
        return plan
    quiz_rows = [
        (row, cells) for row, cells in rows if cells.get("row_type", "").strip() == QUIZ_ROW
    ]
    if target.kind == "new_quiz":
        if not quiz_rows:
            plan.refused = _("A new quiz needs a row with row_type quiz.")
            return plan
        plan.quiz = _quiz_row(quiz_rows[0][0].number, quiz_rows[0][1], plan)
        if plan.quiz is None:
            return plan
        plan.issues += [
            Issue(row.number, "row_type", _("A file can hold only one quiz row."), True)
            for row, _cells in quiz_rows[1:]
        ]
    else:
        plan.issues += [
            Issue(
                row.number, None, _("The quiz row was ignored: the target already exists."), False
            )
            for row, _cells in quiz_rows
        ]
    locales = _target_locales(target, plan)
    plan.unused_columns = _unused(parsed, mapping, target, [cells for _row, cells in rows])
    plan.issues += _dropped_languages([cells for _row, cells in rows], locales)
    for row, cells in rows:
        kind = cells.get("row_type", "").strip()
        if kind == QUIZ_ROW:
            continue
        if kind not in ("", QUESTION_ROW):
            plan.issues.append(Issue(row.number, "row_type", _("Unknown row type."), True))
            continue
        if row.error:
            plan.issues.append(Issue(row.number, None, row.error, True))
            continue
        try:
            question = _question(row.number, cells, locales, parsed.files, check_address)
        except _RowProblem as problem:
            plan.issues.append(Issue(row.number, problem.column, problem.message, True))
            continue
        plan.questions.append(question)
        plan.issues += _gaps(question, locales)
        plan.issues += _blank_correct(question, cells, locales)
    if target.bank is not None and placement is not None:
        _placed(plan, placement)
    if target.replace and any(issue.is_error for issue in plan.issues):
        plan.refused = _(
            "Replacing needs every row to be usable. Fix the rows listed, in the file or in the "
            "folder structure, and check again; nothing was changed."
        )
    return plan


def _free_slug(wanted: str) -> str:
    candidate = wanted
    number = 2
    while Quiz.objects.filter(slug=candidate).exists():
        tail = f"-{number}"
        candidate = f"{wanted[: 80 - len(tail)]}{tail}"
        number += 1
    return candidate


def _created_quiz(planned: PlannedQuiz, admin_id: str) -> tuple[Quiz, list[Issue]]:
    wanted = planned.slug if slug_re.fullmatch(planned.slug) else ""
    wanted = wanted or slugify(planned.title[planned.default_locale])[:80] or "quiz"
    slug = _free_slug(wanted[:80])
    issues = []
    if slug != wanted[:80]:
        message = _("The address %(wanted)s is taken, so the quiz got %(slug)s.")
        issues.append(Issue(planned.row, "slug", message % {"wanted": wanted, "slug": slug}, False))
    title = authoring.free_title(planned.title)
    if title != planned.title:
        message = _("Another quiz already has the title %(wanted)s, so this one got %(title)s.")
        named = {
            "wanted": planned.title[planned.default_locale],
            "title": title[planned.default_locale],
        }
        issues.append(Issue(planned.row, "title", message % named, False))
    quiz = Quiz.objects.create(
        slug=slug,
        title=title,
        description=planned.description,
        default_locale=planned.default_locale,
        supported_locales=planned.locales,
        created_by=admin_id,
    )
    for key, value in planned.setting_values.items():
        settings.set_override(key, quiz, value, admin_id=admin_id)
    return quiz, issues


def _save_to_bank(question: PlannedQuestion, bank: QuestionBank, admin_id: str) -> Issue | None:
    try:
        with transaction.atomic():
            folder = (
                bank_folders.ensure_path(bank, question.folder, admin_id=admin_id)
                if question.folder
                else None
            )
            banks.save_question(
                bank,
                None,
                question.type_id,
                question.config,
                locales=languages(),
                tags=question.tags,
                scoring=question.scoring,
                sources=question.sources,
                explanation=question.explanation,
                admin_id=admin_id,
                setting_values=question.setting_values,
                folder=folder,
            )
    except bank_folders.FolderError as error:
        return Issue(question.row, "folder", str(error), True)
    except banks.NoCompleteLanguage:
        message = _("A bank question must be complete in at least one language.")
        return Issue(question.row, None, message, True)
    return None


def apply(plan: ImportPlan, target: Target, *, admin_id: str) -> Outcome:
    """One transaction. A plan with no question creates nothing. A bank can still refuse a row."""
    issues = list(plan.issues)
    if plan.refused or not plan.questions:
        return Outcome(target.quiz, target.bank, 0, issues)
    if target.replace and any(issue.is_error for issue in plan.issues):
        # a row dropped after the check (an image that failed) must not cost its old question
        raise ReplaceRefused([issue for issue in plan.issues if issue.is_error])
    added = 0
    removed = 0
    with transaction.atomic():
        quiz = target.quiz
        if target.kind == "draft" and quiz is not None:
            authoring.ensure_editable(quiz)
        if target.kind == "new_quiz" and plan.quiz is not None:
            quiz, created = _created_quiz(plan.quiz, admin_id)
            issues += created
        if target.bank is not None:
            old_ids = list(target.bank.questions.values_list("pk", flat=True))
            for question in plan.questions:
                problem = _save_to_bank(question, target.bank, admin_id)
                if problem is None:
                    added += 1
                else:
                    issues.append(problem)
            if target.replace:
                if len(issues) > len(plan.issues):  # a save failed: roll everything back
                    raise ReplaceRefused(issues[len(plan.issues) :])
                removed = target.bank.questions.filter(pk__in=old_ids).delete()[0]
        elif quiz is not None:
            authoring.add_questions(
                quiz,
                [
                    {
                        "type_id": question.type_id,
                        "config": question.config,
                        "points": question.points,
                        "scoring": question.scoring,
                        "sources": question.sources,
                        "explanation": question.explanation,
                        "setting_values": question.setting_values or None,
                    }
                    for question in plan.questions
                ],
            )
            added = len(plan.questions)
        audit.record(
            actor_type="admin",
            actor_id=admin_id,
            action="import.applied",
            entity_type="bank" if target.bank else "quiz",
            entity_id=str(target.bank.pk if target.bank else quiz.pk if quiz else ""),
            details={
                "target": target.kind,
                "added": added,
                **({"replaced": True, "removed": removed} if target.replace else {}),
                "errors": sum(issue.is_error for issue in issues),
                "warnings": sum(not issue.is_error for issue in issues),
            },
        )
    return Outcome(quiz, target.bank, added, issues, removed)
