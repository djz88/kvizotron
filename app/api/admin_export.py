"""Downloading the questions of a quiz or a bank, for editing and importing back (ADR-0045)."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from app.api.admin_auth import admin_required
from app.api.rendering import media_storage
from app.contracts import ExporterProvider
from app.domain import question_export
from app.domain.models import QuestionBank, Quiz
from app.kernel import registry

EXTENSIONS = {
    "image/webp": ".webp",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


def _exporter() -> ExporterProvider:
    try:
        return cast(ExporterProvider, registry.get("exporter", "csv"))
    except LookupError as exc:
        raise Http404 from exc


def _name_of(asset_id: str) -> str:
    storage = media_storage()
    stored = storage.load(asset_id) if storage else None
    extension = EXTENSIONS.get(stored.mime_type, "") if stored else ""
    return f"images/{asset_id}{extension}"


def _files(assets: dict[str, str]) -> dict[str, bytes]:
    storage = media_storage()
    files = {}
    for name, asset_id in assets.items():
        stored = storage.load(asset_id) if storage else None
        if stored is not None:
            files[name] = Path(stored.path).read_bytes()
    return files


def _download(
    request: HttpRequest, data: question_export.ExportData, name: str, kind: str, entity: Any
) -> HttpResponse:
    exported = _exporter().write(data.columns, data.rows, _files(data.assets))
    question_export.record_download(kind, entity, str(request.user.pk), len(data.rows))
    response = HttpResponse(exported.data, content_type=exported.content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}.{exported.extension}"'
    return response


@admin_required
@require_GET
def quiz_export(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    data = question_export.rows_for_quiz(quiz, _name_of)
    return _download(request, data, quiz.slug, "quiz", quiz.pk)


@admin_required
@require_GET
def bank_export(request: HttpRequest, bank_id: UUID) -> HttpResponse:
    bank = get_object_or_404(QuestionBank, pk=bank_id)
    data = question_export.rows_for_bank(bank, _name_of)
    return _download(request, data, f"bank-{bank.pk}", "bank", bank.pk)
