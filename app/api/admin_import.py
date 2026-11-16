"""Import pages: upload, mapping when something does not fit, check, confirm, report (FR-41)."""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from app.api import admin_common, rendering
from app.api.admin_auth import admin_required
from app.api.admin_quizzes import FETCHES_SECONDS as _SAVE_BUDGET
from app.api.rendering import media_storage, page
from app.contracts import (
    ImageAddressInvalid,
    ImageRefused,
    ImporterProvider,
    ImportJob,
    ImportJobGone,
    ImportRefused,
    MediaStorageProvider,
    ParsedFile,
    QuestionTypePlugin,
)
from app.domain import (
    authoring,
    bank_folders,
    banks,
    import_structure,
    question_import,
    questions,
    settings,
)
from app.domain.models import QuestionBank, Quiz
from app.domain.question_import import ImportPlan, Issue, Placement, Target
from app.kernel import registry

FETCHES_SECONDS = _SAVE_BUDGET  # one confirmation counts as one save (ADR-0045)
PREVIEWED = 5
logger = logging.getLogger(__name__)
UNUSED = ""


def _provider() -> ImporterProvider:
    provider = rendering.importer()
    if provider is None:
        raise Http404
    return provider


def _target_of(job_target: Mapping[str, str]) -> Target:
    kind = job_target.get("kind")
    if kind == "new_quiz":
        return Target("new_quiz", None, None)
    if kind == "draft":
        return Target("draft", get_object_or_404(Quiz, pk=job_target["id"]), None)
    if kind in ("bank", "bank_replace"):
        bank = get_object_or_404(QuestionBank, pk=job_target["id"])
        return Target("bank", None, bank, replace=kind == "bank_replace")
    raise Http404


def _parsed_target(value: str) -> dict[str, str]:
    """`new_quiz`, `draft:<id>`, `bank:<id>` or `bank_replace:<id>`, from the button used."""
    kind, _sep, target_id = value.partition(":")
    if kind == "new_quiz" and not target_id:
        return {"kind": kind, "id": ""}
    if kind in ("draft", "bank", "bank_replace"):
        try:
            UUID(target_id)
        except ValueError as exc:
            raise Http404 from exc
        return {"kind": kind, "id": target_id}
    raise Http404


def _target_label(target: Target) -> str:
    if target.quiz is not None:
        title = target.quiz.title.get(target.quiz.default_locale) or target.quiz.slug
        return _("Into the draft of %(title)s") % {"title": title}
    if target.bank is not None and target.replace:
        return _("Replace the questions of the bank %(name)s") % {"name": target.bank.name}
    if target.bank is not None:
        return _("Into the bank %(name)s") % {"name": target.bank.name}
    return _("As a new quiz")


def _back_url(target: Target) -> str:
    if target.quiz is not None:
        return reverse("admin_quiz_edit", args=[target.quiz.id])
    if target.bank is not None:
        return reverse("admin_bank", args=[target.bank.id])
    return reverse("admin_quizzes")


def _gone(request: HttpRequest) -> HttpResponse:
    context = {"message": _("This import is no longer available. Upload the file again.")}
    return page(request, "admin/import_gone.html", context, request.locale, status=404)  # type: ignore[attr-defined]


def _guide(name: str, content_type: str) -> HttpResponse:
    response = HttpResponse(_provider().guide(name), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@admin_required
@require_GET
def sample(request: HttpRequest) -> HttpResponse:
    return _guide("quiz-sample.csv", "text/csv; charset=utf-8")


@admin_required
@require_GET
def format_description(request: HttpRequest) -> HttpResponse:
    return _guide("csv-format.md", "text/markdown; charset=utf-8")


@admin_required
def new(request: HttpRequest) -> HttpResponse:
    provider = _provider()
    value = request.GET.get("target", "")
    job_target = _parsed_target(value)
    target = _target_of(job_target)
    error = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            error = _("Choose a file.")
        else:
            try:
                job_id = provider.begin(admin_common.admin_id(request), job_target, upload.chunks())
            except ImportRefused as refused:
                error = str(refused)
            else:
                parsed = provider.read(job_id)
                unknown = question_import.unknown_columns(parsed.columns)
                return redirect("admin_import_mapping" if unknown else "admin_import_check", job_id)
    context = {
        "target_value": value,
        "target_label": _target_label(target),
        "back_url": _back_url(target),
        "error": error,
    }
    return page(request, "admin/import_upload.html", context, request.locale)  # type: ignore[attr-defined]


def _job(provider: ImporterProvider, request: HttpRequest, job_id: UUID) -> ImportJob:
    return provider.job(str(job_id), admin_common.admin_id(request))


@admin_required
def mapping(request: HttpRequest, job_id: UUID) -> HttpResponse:
    provider = _provider()
    try:
        job = _job(provider, request, job_id)
        if job.report is not None:
            return redirect("admin_import_report", job.id)
        parsed = provider.read(job.id)
    except ImportJobGone, ImportRefused:
        return _gone(request)
    unknown = question_import.unknown_columns(parsed.columns)
    known = question_import.known_columns()
    chosen = {column: job.mapping.get(column, UNUSED) for column in unknown}
    error = None
    if request.method == "POST":
        chosen = {column: request.POST.get(f"map_{column}", UNUSED) for column in unknown}
        used = [target for target in chosen.values() if target]
        clash = set(used) & set(parsed.columns) or len(set(used)) != len(used)
        if clash or not set(used) <= known:
            error = _(
                "Each target can be used once, and only if the file does not have it already."
            )
        else:
            provider.set_mapping(job.id, chosen)
            return redirect("admin_import_check", job.id)
    samples = {
        column: next((row.cells[column] for row in parsed.rows if row.cells.get(column)), "")
        for column in unknown
    }
    context = {
        "job_id": job.id,
        "rows": [
            {"column": column, "sample": samples[column], "chosen": chosen[column]}
            for column in unknown
        ],
        "targets": sorted(known),
        "error": error,
    }
    return page(request, "admin/import_mapping.html", context, request.locale)  # type: ignore[attr-defined]


def _check_address(storage: MediaStorageProvider | None) -> Any:
    return storage.check_image_address if storage is not None else None


def _plan(
    job: ImportJob, parsed: ParsedFile, target: Target, placement: Placement | None = None
) -> ImportPlan:
    return question_import.interpret(
        parsed, target, job.mapping, _check_address(media_storage()), placement=placement
    )


@dataclass
class _Placing:
    """The folder structure chosen on the check page, read from its address or the confirm form."""

    placement: Placement | None = None
    error: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    tops: list[str] = field(default_factory=list)


def _placing(
    job: ImportJob, parsed: ParsedFile, target: Target, source: Mapping[str, str]
) -> _Placing:
    if target.bank is None:
        return _Placing()
    tops = question_import.top_folders(parsed, job.mapping)
    names = ["under", "added", *(f"name_{index}" for index in range(len(tops)))]
    values = {name: source.get(name, "").strip() for name in names if source.get(name, "").strip()}
    values |= {
        f"drop_{index}": "1" for index in range(len(tops)) if source.get(f"drop_{index}") == "1"
    }
    try:
        return _Placing(question_import.placement_of(target.bank, values, tops), None, values, tops)
    except question_import.PlacementInvalid as invalid:
        return _Placing(None, str(invalid), values, tops)


def _structure_view(plan: ImportPlan, target: Target, placing: _Placing) -> dict[str, Any] | None:
    if target.bank is None or not (plan.questions or placing.tops):
        return None
    return {
        "bank": target.bank.name,
        "tree": import_structure.structure(plan, target.bank),
        "short_rows": import_structure.short_rows(plan, target.bank) if target.replace else [],
        "under_choices": bank_folders.choices(target.bank),
        "tops": [
            {
                "index": index,
                "name": top,
                "value": placing.values.get(f"name_{index}", top),
                "dropped": f"drop_{index}" in placing.values,
            }
            for index, top in enumerate(placing.tops)
        ],
        "chosen": placing.values,
        "error": placing.error,
    }


def _issue_view(request: HttpRequest) -> dict[str, Any]:
    """A long list of issues scrolls in its own table; `?all=1` shows every row on the page."""
    query = request.GET.copy()
    showing_all = query.get("all") == "1"
    query["all"] = "1"
    all_url = "?" + query.urlencode()
    query.pop("all")
    return {"all": showing_all, "all_url": all_url, "scroll_url": "?" + query.urlencode()}


def _issue_rows(issues: list[Issue]) -> list[dict[str, Any]]:
    return [
        {"row": issue.row or "", "column": issue.column or "", "message": issue.message}
        for issue in sorted(issues, key=lambda issue: issue.row or 0)
    ]


def _preview_rows(plan: ImportPlan, locales: list[str]) -> list[dict[str, Any]]:
    rows = []
    for question in plan.questions[:PREVIEWED]:
        plugin = cast(QuestionTypePlugin, registry.get("question_type", question.type_id))
        rows.append(
            {
                "row": question.row,
                "lines": [
                    {"label": line.label, "locale": line.locale, "value": line.value}
                    for line in plugin.describe_definition(question.config, locales)
                ],
            }
        )
    return rows


def _locales(plan: ImportPlan, target: Target) -> list[str]:
    if plan.quiz is not None:
        return plan.quiz.locales
    if target.quiz is not None:
        return list(target.quiz.supported_locales)
    return question_import.languages()


@admin_required
def check(request: HttpRequest, job_id: UUID) -> HttpResponse:
    provider = _provider()
    try:
        job = _job(provider, request, job_id)
        if job.report is not None:
            return redirect("admin_import_report", job.id)
        parsed = provider.read(job.id)
    except ImportJobGone, ImportRefused:
        return _gone(request)
    target = _target_of(job.target)
    placing = _placing(job, parsed, target, request.GET)
    plan = _plan(job, parsed, target, placing.placement)
    context = {
        "job_id": job.id,
        "structure": _structure_view(plan, target, placing),
        "placement_values": placing.values,
        "placement_error": placing.error,
        "lang": request.GET.get("lang", ""),
        "target_label": _target_label(target),
        "refused": plan.refused,
        "replace": _replace_view(target),
        "count": len(plan.questions),
        "errors": _issue_rows([issue for issue in plan.issues if issue.is_error]),
        "warnings": _issue_rows([issue for issue in plan.issues if not issue.is_error]),
        "unused": plan.unused_columns,
        "preview": _preview_rows(plan, _locales(plan, target)),
        "upload_again": f"{reverse('admin_import_new')}?target={_target_value(job)}",
        "issue_view": _issue_view(request),
    }
    return page(request, "admin/import_check.html", context, request.locale)  # type: ignore[attr-defined]


def _replace_view(target: Target) -> dict[str, Any] | None:
    """What a replace would delete and who draws from the bank, for the check page."""
    if target.bank is None or not target.replace:
        return None
    return {"removed": target.bank.questions.count(), "quizzes": banks.used_by(target.bank)}


def _target_value(job: ImportJob) -> str:
    kind = job.target.get("kind", "")
    return kind if kind == "new_quiz" else f"{kind}:{job.target.get('id', '')}"


def _resolve_images(
    plan: ImportPlan, job_id: str, provider: ImporterProvider, storage: MediaStorageProvider | None
) -> None:
    """After the plan and outside any transaction: this is the slow part (ADR-0045).

    A file that cannot be used costs its row, as it is wrong and will stay wrong. An address that
    fails keeps the question, as it may work next time, and the next save of the question retries.
    """
    if storage is None:
        return
    deadline = time.monotonic() + FETCHES_SECONDS
    allow_internal = settings.internal_addresses_allowed()
    assets: dict[str, str | None] = {}
    kept = []
    for question in plan.questions:
        try:
            for found in questions.images_of(question.config):
                image = cast(dict[str, Any], found)
                cell = str(image["source"])
                if question_import.is_address(cell):
                    if cell not in assets:
                        assets[cell] = _fetched(storage, cell, allow_internal, deadline)
                    image["asset"] = assets[cell]
                    if assets[cell] is None:
                        message = _("The image at %(address)s could not be fetched.")
                        plan.issues.append(
                            Issue(question.row, None, message % {"address": cell}, False)
                        )
                else:
                    image["asset"] = storage.store_image(provider.read_image(job_id, cell))
                    del image["source"]
        except (ImportRefused, ImageRefused) as error:
            plan.issues.append(Issue(question.row, None, str(error), True))
        else:
            kept.append(question)
    plan.questions = kept


def _fetched(
    storage: MediaStorageProvider, address: str, allow_internal: bool, deadline: float
) -> str | None:
    if time.monotonic() >= deadline:
        return None
    try:
        return storage.fetch_image(address, allow_internal=allow_internal, deadline=deadline)
    except ImageAddressInvalid:
        raise
    except ImageRefused:
        return None


def _report(plan: ImportPlan, outcome: question_import.Outcome | None) -> dict[str, Any]:
    issues = outcome.issues if outcome is not None else plan.issues
    if outcome is not None and outcome.quiz is not None:
        link = reverse("admin_quiz_edit", args=[outcome.quiz.id])
    elif outcome is not None and outcome.bank is not None:
        link = reverse("admin_bank", args=[outcome.bank.id])
    else:
        link = None
    return {
        "added": outcome.added if outcome is not None else 0,
        "removed": outcome.removed if outcome is not None else 0,
        "errors": _issue_rows([issue for issue in issues if issue.is_error]),
        "warnings": _issue_rows([issue for issue in issues if not issue.is_error]),
        "unused": plan.unused_columns,
        "refused": plan.refused,
        "link": link,
    }


def _confirmed(
    job: ImportJob, provider: ImporterProvider, admin_id: str, source: Mapping[str, str]
) -> dict[str, Any]:
    target = _target_of(job.target)
    parsed = provider.read(job.id)
    placing = _placing(job, parsed, target, source)
    plan = _plan(job, parsed, target, placing.placement)
    outcome = None
    if placing.error is not None:
        message = _("The folder structure is no longer valid: %(reason)s Nothing was imported.")
        plan.refused = message % {"reason": placing.error}
    if plan.refused is None:
        _resolve_images(plan, job.id, provider, media_storage())
        try:
            outcome = question_import.apply(plan, target, admin_id=admin_id)
        except authoring.QuizArchived:
            plan.refused = _("This quiz was archived in the meantime. Nothing was imported.")
        except question_import.ReplaceRefused as refused:
            plan.issues.extend(issue for issue in refused.issues if issue not in plan.issues)
            plan.refused = _("A row could not be saved, so nothing was replaced.")
    return _report(plan, outcome)


@admin_required
@require_POST
def confirm(request: HttpRequest, job_id: UUID) -> HttpResponse:
    provider = _provider()
    try:
        job = _job(provider, request, job_id)
        if not provider.claim(job.id):  # a repeated request: the first one is doing it or did it
            return redirect("admin_import_report", job.id)
    except ImportJobGone:
        return _gone(request)
    try:
        report_data = _confirmed(job, provider, admin_common.admin_id(request), request.POST)
    except Exception:  # the job was claimed, so it must end, or it could never be tried again
        logger.exception("Import %s failed", job.id)
        report_data = {"failed": True}
    provider.finish(job.id, report_data)
    return redirect("admin_import_report", job.id)


@admin_required
def report(request: HttpRequest, job_id: UUID) -> HttpResponse:
    provider = _provider()
    try:
        job = _job(provider, request, job_id)
    except ImportJobGone:
        return _gone(request)
    context = {"report": job.report, "issue_view": _issue_view(request)}
    return page(request, "admin/import_report.html", context, request.locale)  # type: ignore[attr-defined]
