"""Question banks, and the rows of a quiz that draw from them."""

import secrets
import uuid
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from markupsafe import Markup

from app.api import rendering
from app.api.admin_auth import admin_required
from app.api.admin_common import uuid_or_404
from app.api.admin_forms import BankForm, BankQuestionForm, DrawForm
from app.api.admin_quizzes import (
    _add_menu,
    _enabled_plugin,
    _strategies,
    not_archived,
    read_question_form,
    setting_initial,
)
from app.api.i18n import PUBLIC_LOCALES
from app.api.inline_name import NameField, render_field, wants_partial
from app.api.rendering import page, question_label, with_media_urls
from app.contracts import QuestionTypePlugin
from app.domain import authoring, bank_folders, banks
from app.domain.models import BankFolder, BankQuestion, QuestionBank, Quiz
from app.domain.questions import has_image_without_copy


def _folder_of(bank: QuestionBank, value: str) -> BankFolder | None:
    """A folder of this bank named by id; an empty value is no folder, a bad one a 404."""
    if not value:
        return None
    try:
        return get_object_or_404(BankFolder, pk=UUID(value), bank=bank)
    except ValueError:
        raise Http404 from None


def _question_rows(
    rows: Iterable[BankQuestion], paths: dict[Any, str], locale: str
) -> list[dict[str, Any]]:
    """The texts in the language chosen; a question without it shows its first language, marked."""
    found = []
    for row in rows:
        complete = banks.complete_locales(row, PUBLIC_LOCALES)
        lacks = locale not in complete and bool(complete)
        shown = complete[0] if lacks else locale
        found.append(
            {
                "id": row.pk,
                "label": question_label(row.question_json, shown),
                "shown_language": shown,
                "lacks_language": lacks,
                "tags": row.tags,
                "path": paths.get(row.folder_id, ""),
                "folder_id": row.folder_id,
                "complete": complete,
                "no_copy": has_image_without_copy(row.question_json),
            }
        )
    return found


def _language_chips(
    request: HttpRequest, counts: dict[str, int], chosen: str
) -> list[dict[str, Any]]:
    """Links that change only the language: the folder and the search stay."""
    keep = [(key, value) for key, value in request.GET.items() if key != "view_lang"]
    return [
        {
            "code": code,
            "count": count,
            "current": code == chosen,
            "href": "?" + urlencode([*keep, ("view_lang", code)]),
        }
        for code, count in counts.items()
    ]


def _subtree_ids(node: bank_folders.FolderNode) -> set[str]:
    return {str(node.folder.pk)}.union(*(_subtree_ids(child) for child in node.children))


def _other_banks(bank: QuestionBank) -> list[dict[str, Any]]:
    return [
        {"bank": other, "folders": bank_folders.choices(other)}
        for other in QuestionBank.objects.exclude(pk=bank.pk).order_by("name")
    ]


def _find(nodes: list[bank_folders.FolderNode], folder_id: Any) -> bank_folders.FolderNode | None:
    for node in nodes:
        if node.folder.pk == folder_id:
            return node
        found = _find(node.children, folder_id)
        if found is not None:
            return found
    return None


def _bank_page(
    request: HttpRequest,
    bank: QuestionBank,
    error: str | None = None,
    status: int = 200,
    folder_param: str | None = None,
    name_field: NameField | None = None,
    folder_field: NameField | None = None,
) -> HttpResponse:
    """One level at a time, like a file explorer: the folder asked for, or the top."""
    param = request.GET.get("folder", "") if folder_param is None else folder_param
    query = request.GET.get("q", "").strip() if folder_param is None else ""
    current = None if param == "none" else _folder_of(bank, param)
    paths = {UUID(folder_id): path for folder_id, path in bank_folders.choices(bank)}
    nodes = bank_folders.tree(bank)
    if query:
        rows = bank_folders.search(bank, query)
    elif current is not None:
        rows = list(current.questions.order_by("id"))
    else:
        rows = list(bank.questions.filter(folder__isnull=True).order_by("id"))
    if current is not None:
        found = _find(nodes, current.pk)
        shown = found.children if found else []
    else:
        shown = [] if param == "none" else nodes
    crumbs, walk = [], current
    while walk is not None:
        crumbs.append(walk)
        walk = walk.parent
    language_counts = banks.language_counts(bank, PUBLIC_LOCALES)
    view_lang = request.GET.get("view_lang", "")
    if view_lang not in language_counts:
        view_lang = next(iter(language_counts), PUBLIC_LOCALES[0])
    current_id = str(current.pk) if current else ""
    asked = request.GET.get("edit", "") if request.method == "GET" else ""
    editing_id = asked.removeprefix("folder:") if asked.startswith("folder:") else ""
    overrides = {folder_field.key: folder_field} if folder_field else {}

    def field_for(folder: BankFolder, variant: str) -> NameField:
        key = str(folder.pk)
        return overrides.get(key) or _folder_field(
            bank, folder, next_folder=current_id, variant=variant, editing=key == editing_id
        )

    context = {
        "folder_fields": {str(node.folder.pk): field_for(node.folder, "row") for node in shown},
        "current_field": field_for(current, "heading") if current else None,
        "can_import": rendering.can_import(),
        "question_total": bank.questions.count(),
        "bank": bank,
        "name_field": name_field
        or _name_field(bank, editing=request.method == "GET" and request.GET.get("edit") == "name"),
        "questions": _question_rows(rows, paths, view_lang),
        "language_chips": _language_chips(request, language_counts, view_lang),
        "view_lang": view_lang,
        "query": query,
        "current": current,
        "crumbs": crumbs[::-1],
        "unfiled": bank_folders.unfiled_count(bank),
        "folders": shown,
        "destinations": {
            str(node.folder.pk): [
                (i, path) for i, path in bank_folders.choices(bank) if i not in _subtree_ids(node)
            ]
            for node in shown
        },
        "other_banks": _other_banks(bank),
        "folder_choices": bank_folders.choices(bank),
        "question_types": _add_menu(),
        "error": error,
    }
    return page(request, "admin/bank.html", context, request.locale, status=status)  # type: ignore[attr-defined]


def _back(bank: QuestionBank, folder_param: str) -> HttpResponse:
    url = reverse("admin_bank", args=[bank.id])
    return redirect(f"{url}?folder={folder_param}" if folder_param else url)


@admin_required
def banks_page(request: HttpRequest) -> HttpResponse:
    form = BankForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        bank = banks.create(form.cleaned_data["name"], admin_id=str(request.user.pk))
        return redirect("admin_bank", bank.id)
    context = {
        "form": form,
        "banks": [
            {"bank": bank, "count": bank.questions.count()}
            for bank in QuestionBank.objects.order_by("name")
        ],
    }
    return page(request, "admin/banks.html", context, request.locale)  # type: ignore[attr-defined]


@admin_required
@require_GET
def bank_page(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    return _bank_page(request, bank)


def _name_field(
    bank: QuestionBank,
    *,
    editing: bool = False,
    value: str | None = None,
    error: str = "",
    saved: bool = False,
) -> NameField:
    page_url = reverse("admin_bank", args=[bank.id])
    name_url = reverse("admin_bank_name", args=[bank.id])
    return NameField(
        label=_("Bank name"),
        field="name",
        key=str(bank.id),
        value=bank.name if value is None else value,
        save_url=name_url,
        edit_url=f"{name_url}?edit=1",
        view_url=name_url,
        edit_page=f"{page_url}?edit=name",
        back_page=page_url,
        max_length=120,
        editing=editing,
        error=error,
        saved=saved,
        tag="h1",
    )


@admin_required
@require_http_methods(["GET", "POST"])
def bank_name(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    """The name of a bank on the spot: the display, the field, and the save (AC-160)."""
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    if request.method == "GET":
        editing = request.GET.get("edit") == "1"
        if not wants_partial(request):
            suffix = "?edit=name" if editing else ""
            return redirect(reverse("admin_bank", args=[bank.id]) + suffix)
        return render_field(request, _name_field(bank, editing=editing))
    form = BankForm(request.POST)
    if not form.is_valid():
        error = " ".join(form.errors.get("name", []))
        field = _name_field(bank, editing=True, value=request.POST.get("name", ""), error=error)
        if wants_partial(request):
            return render_field(request, field, status=400)
        return _bank_page(request, bank, status=400, folder_param="", name_field=field)
    banks.rename(bank, form.cleaned_data["name"], admin_id=str(request.user.pk))
    if wants_partial(request):
        bank.refresh_from_db()
        return render_field(request, _name_field(bank, saved=True))
    return redirect("admin_bank", bank.id)


@admin_required
@require_POST
def bank_delete(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    try:
        banks.delete(bank, admin_id=str(request.user.pk))
    except banks.BankInUse as error:
        message = _("This bank is used by these quizzes: %(quizzes)s") % {
            "quizzes": ", ".join(error.quizzes)
        }
        return _bank_page(request, bank, message, status=409)
    return redirect("admin_banks")


def _question_page(
    request: HttpRequest,
    bank: QuestionBank,
    plugin: QuestionTypePlugin,
    config: Any,
    common: BankQuestionForm,
    form_key: str | None,
    error: str | None = None,
) -> HttpResponse:
    context = {
        "type_label": plugin.label(),
        "editor": Markup(  # noqa: S704  # the plugin escapes through its own template
            plugin.render_admin(with_media_urls(config, keep_asset=True), PUBLIC_LOCALES)
        ),
        "common_form": common,
        "form_key": form_key,
        "error": error,
        "back_url": reverse("admin_bank", args=[bank.id]),
        "editor_kind": "bank",
    }
    return page(request, "admin/question_form.html", context, request.locale)  # type: ignore[attr-defined]


def _save_question(
    request: HttpRequest,
    bank: QuestionBank,
    plugin: QuestionTypePlugin,
    question_id: str | None,
    current: Any,
) -> HttpResponse:
    common = BankQuestionForm(
        request.POST,
        strategies=_strategies(plugin),
        locales=PUBLIC_LOCALES,
        plugin=plugin,
        folders=bank_folders.choices(bank),
    )
    key = request.POST.get("form_key", "") if question_id is None else None
    config, message = read_question_form(request, plugin, PUBLIC_LOCALES, current)
    if message or not common.is_valid():
        return _question_page(request, bank, plugin, config, common, key, message)
    try:
        banks.save_question(
            bank,
            question_id,
            plugin.id,
            config,
            locales=PUBLIC_LOCALES,
            tags=common.cleaned_data["tags"],
            scoring=common.cleaned_data["scoring"] or None,
            sources=common.cleaned_data["sources"],
            explanation=common.explanation(),
            new_id=str(uuid.uuid5(bank.id, key)) if key else None,
            admin_id=str(request.user.pk),
            setting_values=common.setting_values(),
            folder=_folder_of(bank, common.cleaned_data["folder"]),
        )
    except banks.NoCompleteLanguage:
        message = _("Complete the question in at least one language.")
        return _question_page(request, bank, plugin, config, common, key, message)
    return redirect("admin_bank", bank.id)


@admin_required
def bank_question_new(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    plugin = _enabled_plugin(request.GET.get("type", ""))
    if request.method == "POST":
        return _save_question(request, bank, plugin, None, {})
    config = plugin.initial(request.GET.get("preset", ""), PUBLIC_LOCALES)
    common = BankQuestionForm(
        initial={"folder": request.GET.get("folder", "")},
        strategies=_strategies(plugin),
        locales=PUBLIC_LOCALES,
        plugin=plugin,
        folders=bank_folders.choices(bank),
    )
    return _question_page(request, bank, plugin, config, common, secrets.token_urlsafe(16))


@admin_required
def bank_question_edit(request: HttpRequest, bank_id: UUID, question_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    row = get_object_or_404(BankQuestion, pk=question_id, bank=bank)
    question = row.question_json
    plugin = _enabled_plugin(question["type"])
    if request.method == "POST":
        return _save_question(request, bank, plugin, str(row.pk), question["definition"])
    initial = {
        "scoring": question["scoring"],
        "sources": "\n".join(question.get("sources", [])),
        "tags": ", ".join(row.tags),
        "folder": str(row.folder_id or ""),
        **setting_initial(question),
        **{
            f"explanation_{locale}": text
            for locale, text in question.get("explanation", {}).items()
        },
    }
    common = BankQuestionForm(
        initial=initial,
        strategies=_strategies(plugin),
        locales=PUBLIC_LOCALES,
        plugin=plugin,
        folders=bank_folders.choices(bank),
    )
    return _question_page(request, bank, plugin, question["definition"], common, None)


@admin_required
@require_POST
def bank_question_delete(request: HttpRequest, bank_id: UUID, question_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    banks.delete_question(bank, question_id, admin_id=str(request.user.pk))
    return redirect("admin_bank", bank.id)


def _run_folder_action(
    request: HttpRequest, bank: QuestionBank, action: Callable[[], object]
) -> HttpResponse:
    """A refused action shows its message on the page the admin came from."""
    folder_param = request.POST.get("next_folder", "")
    try:
        action()
    except bank_folders.FolderError as error:
        return _bank_page(request, bank, str(error), status=400, folder_param=folder_param)
    return _back(bank, folder_param)


@admin_required
@require_POST
def folder_create(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    parent = _folder_of(bank, request.POST.get("parent", ""))
    name = request.POST.get("name", "")
    admin_id = str(request.user.pk)
    return _run_folder_action(
        request, bank, lambda: bank_folders.create(bank, parent, name, admin_id=admin_id)
    )


def _folder_field(
    bank: QuestionBank,
    folder: BankFolder,
    *,
    next_folder: str = "",
    variant: str = "row",
    editing: bool = False,
    value: str | None = None,
    error: str = "",
    saved: bool = False,
) -> NameField:
    """A folder's name as a row of a list (a link to the folder) or as the heading of its page."""
    page_url = reverse("admin_bank", args=[bank.id])
    rename_url = reverse("admin_bank_folder_rename", args=[bank.id, folder.pk])
    keep = urlencode({"variant": variant, "next_folder": next_folder})
    back = f"{page_url}?folder={next_folder}" if next_folder else page_url
    return NameField(
        label=_("Folder name"),
        field="name",
        key=str(folder.pk),
        value=folder.name if value is None else value,
        save_url=rename_url,
        edit_url=f"{rename_url}?{keep}&edit=1",
        view_url=f"{rename_url}?{keep}",
        edit_page=f"{back}{'&' if next_folder else '?'}edit=folder:{folder.pk}",
        back_page=back,
        max_length=bank_folders.MAX_NAME,
        editing=editing,
        error=error,
        saved=saved,
        link="" if variant == "heading" else f"{page_url}?folder={folder.pk}",
        mirror=f"crumb-{folder.pk}" if variant == "heading" else "",
        tag="h2" if variant == "heading" else "span",
        hidden={"variant": variant, "next_folder": next_folder},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def folder_rename(request: HttpRequest, bank_id: UUID, folder_id: UUID) -> HttpResponse:
    """The name of a folder on the spot, in its row or as the heading of its page (AC-160)."""
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    folder = get_object_or_404(BankFolder, pk=folder_id, bank=bank)
    source = request.POST if request.method == "POST" else request.GET
    variant = "heading" if source.get("variant") == "heading" else "row"
    next_folder = source.get("next_folder", "")
    shown = {"next_folder": next_folder, "variant": variant}
    if request.method == "GET":
        editing = request.GET.get("edit") == "1"
        if not wants_partial(request):
            field = _folder_field(bank, folder, **shown)
            return redirect(field.edit_page if editing else field.back_page)
        return render_field(request, _folder_field(bank, folder, editing=editing, **shown))
    name = request.POST.get("name", "")
    try:
        bank_folders.rename(folder, name, admin_id=str(request.user.pk))
    except bank_folders.FolderError as error:
        field = _folder_field(bank, folder, editing=True, value=name, error=str(error), **shown)
        if wants_partial(request):
            return render_field(request, field, status=400)
        return _bank_page(request, bank, status=400, folder_param=next_folder, folder_field=field)
    if wants_partial(request):
        folder.refresh_from_db()
        return render_field(request, _folder_field(bank, folder, saved=True, **shown))
    return _back(bank, next_folder)


NEW_BANK = "newbank"
OTHER_BANK = "bank:"


def _destination(bank: QuestionBank, value: str) -> tuple[QuestionBank, BankFolder | None]:
    """`""` is the top of this bank, `bank:<id>` the top of another, anything else a folder."""
    if not value:
        return bank, None
    if value.startswith(OTHER_BANK):
        return get_object_or_404(QuestionBank, pk=uuid_or_404(value[len(OTHER_BANK) :])), None
    folder = get_object_or_404(BankFolder.objects.select_related("bank"), pk=uuid_or_404(value))
    return folder.bank, folder


def _move_page(
    request: HttpRequest,
    bank: QuestionBank,
    folder: BankFolder,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    """A page of its own, so a move does not depend on a select inside a menu."""
    blocked = {str(pk) for pk in bank_folders.subtree_ids(folder)}
    context = {
        "bank": bank,
        "folder": folder,
        "path": bank_folders.path_of(folder),
        "destinations": [(i, path) for i, path in bank_folders.choices(bank) if i not in blocked],
        "other_banks": _other_banks(bank),
        "selected": str(folder.parent_id or ""),
        "cancel_url": f"{reverse('admin_bank', args=[bank.id])}?folder={folder.parent_id or ''}",
        "error": error,
    }
    return page(request, "admin/bank_folder_move.html", context, request.locale, status=status)  # type: ignore[attr-defined]


@admin_required
@require_http_methods(["GET", "POST"])
def folder_move(request: HttpRequest, bank_id: UUID, folder_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    folder = get_object_or_404(BankFolder, pk=folder_id, bank=bank)
    if request.method == "GET":
        return _move_page(request, bank, folder)
    value, admin_id = request.POST.get("parent", ""), str(request.user.pk)
    try:
        if value == NEW_BANK:
            return redirect("admin_bank", bank_folders.promote(folder, admin_id=admin_id).id)
        target, parent = _destination(bank, value)
        bank_folders.transfer(folder, target, parent, admin_id=admin_id)
    except bank_folders.FolderError as error:
        return _move_page(request, bank, folder, str(error), 400)
    if target.id == bank.id:
        return _back(bank, str(folder.pk))  # to the folder itself, so its new place shows
    return redirect(f"{reverse('admin_bank', args=[target.id])}?folder={folder.pk}")


@admin_required
@require_POST
def folder_delete(request: HttpRequest, bank_id: UUID, folder_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    folder = get_object_or_404(BankFolder, pk=folder_id, bank=bank)
    admin_id = str(request.user.pk)
    return _run_folder_action(request, bank, lambda: bank_folders.delete(folder, admin_id=admin_id))


@admin_required
@require_POST
def questions_move(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    chosen = request.POST.getlist("question")
    folder = _folder_of(bank, request.POST.get("folder", ""))
    admin_id = str(request.user.pk)

    def move() -> None:
        if not chosen:
            raise bank_folders.FolderError(_("Choose the questions to move."))
        try:
            bank_folders.move_questions(bank, chosen, folder, admin_id=admin_id)
        except ValueError, ValidationError:
            raise bank_folders.WrongBank(_("A chosen question is not in this bank.")) from None

    return _run_folder_action(request, bank, move)


def _bank_choices() -> Sequence[tuple[str, str]]:
    return [(str(bank.id), bank.name) for bank in QuestionBank.objects.order_by("name")]


def _all_tags() -> list[str]:
    tags = {tag for bank in QuestionBank.objects.all() for tag in banks.tags_of(bank)}
    return sorted(tags, key=banks.normal_tag)


def _folder_choices() -> list[tuple[str, str, str]]:
    found = []
    for bank in QuestionBank.objects.order_by("name"):
        for folder_id, path in bank_folders.choices(bank):
            found.append((folder_id, f"{bank.name} / {path}", str(bank.id)))
    return found


def _draw_form(quiz: Quiz, *args: Any, **kwargs: Any) -> DrawForm:
    return DrawForm(
        *args,
        banks=_bank_choices(),
        own_questions=len(authoring.editable_questions(quiz)),
        tags=_all_tags(),
        folders=_folder_choices(),
        **kwargs,
    )


def _draw_page(
    request: HttpRequest, quiz: Quiz, form: DrawForm, gone_folder: str = ""
) -> HttpResponse:
    context = {
        "quiz": quiz,
        "form": form,
        "has_banks": bool(_bank_choices()),
        "gone_folder": gone_folder,
    }
    return page(request, "admin/draw_form.html", context, request.locale)  # type: ignore[attr-defined]


def _save_draw(request: HttpRequest, quiz: Quiz, draw_id: str | None) -> HttpResponse:
    form = _draw_form(quiz, request.POST)
    if not form.is_valid():
        return _draw_page(request, quiz, form)
    data = form.cleaned_data
    authoring.save_draw(
        quiz,
        draw_id,
        bank_id=data["bank"],
        tag=data["tag"],
        difficulty=data["difficulty"],
        folder_id=data["folder"],
        count=data["count"],
        points=data["points"],
        position=data["position"],
    )
    return redirect("admin_quiz_edit", quiz.id)


@admin_required
@not_archived
def draw_new(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    if request.method == "POST":
        return _save_draw(request, quiz, None)
    initial = {"count": 5, "points": 1, "position": len(authoring.editable_questions(quiz))}
    return _draw_page(request, quiz, _draw_form(quiz, initial=initial))


def _existing_draw(quiz: Quiz, draw_id: str) -> dict[str, Any]:
    for row in authoring.editable_draws(quiz):
        if row["id"] == draw_id:
            return row
    raise Http404


@admin_required
@not_archived
def draw_edit(request: HttpRequest, quiz_id: UUID, draw_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    row = _existing_draw(quiz, draw_id)
    if request.method == "POST":
        return _save_draw(request, quiz, draw_id)
    initial = {
        "bank": row["bank_id"],
        "tag": row["tag"],
        "difficulty": row.get("difficulty", ""),
        "folder": row.get("folder_id", ""),
        "count": row["count"],
        "points": row["points"],
        "position": row["position"],
    }
    form = _draw_form(quiz, initial=initial)
    wanted = row.get("folder_id", "")
    gone = bool(wanted) and wanted not in {
        folder_id for folder_id, _label in form.fields["folder"].choices
    }
    return _draw_page(request, quiz, form, row.get("folder_path", "") if gone else "")


@admin_required
@not_archived
@require_POST
def draw_delete(request: HttpRequest, quiz_id: UUID, draw_id: str) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    _existing_draw(quiz, draw_id)
    authoring.delete_draw(quiz, draw_id)
    return redirect("admin_quiz_edit", quiz.id)
