"""Runs results export jobs in a daemon thread of the app process (D2).

There is no scheduler: a submit, a page load and the end of a job each call `kick()`, which starts
every queued job that has a free slot. The provider decides the slots in `claim_next()`.
"""

import functools
import logging
import threading
from collections.abc import Callable, Sequence
from typing import cast

from django.db import connection

from app.api.rendering import media_storage
from app.contracts import ExportJobView, ResultsExporterProvider
from app.domain import results_export
from app.domain.models import Quiz, QuizRun
from app.kernel import registry

logger = logging.getLogger(__name__)


def _thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="kvz-export", daemon=True).start()


SPAWN: Callable[[Callable[[], None]], None] = _thread


def provider() -> ResultsExporterProvider | None:
    try:
        return cast(ResultsExporterProvider, registry.get("results_exporter", "csv"))
    except LookupError:
        return None


def kick() -> None:
    """Start what may run now. Each claim moves a job out of `queued`, so this ends."""
    exporter = provider()
    if exporter is None:
        return
    while (job := exporter.claim_next()) is not None:
        try:
            SPAWN(functools.partial(_run, job))
        except Exception:  # no thread: free the slot instead of holding it as running
            logger.exception("results export %s could not start", job.id)
            exporter.fail(job.id, "error")


def _photos(runs: Sequence[QuizRun]) -> dict[str, str]:
    """Name in the ZIP -> file on disk; a photo whose file is gone is left out."""
    storage = media_storage()
    found: dict[str, str] = {}
    if storage is None:
        return found
    for name, asset_id in results_export.photo_files(runs).items():
        stored = storage.load(asset_id)
        if stored is not None:
            found[name] = stored.path
    return found


def _write(exporter: ResultsExporterProvider, job: ExportJobView) -> None:
    choices = job.choices
    quiz = Quiz.objects.get(pk=choices["quiz"])
    runs = results_export.runs_for(quiz, None if choices.get("all_runs") else choices["runs"])
    files = [str(name) for name in choices["files"]]
    photos = bool(choices.get("photos"))
    bundle = choices.get("bundle") == "zip"
    tables = results_export.tables(runs, files, str(choices["locale"]), photos=photos)
    exporter.write(job.id, tables, _photos(runs) if bundle and photos else {}, bundle)


def _run(job: ExportJobView) -> None:
    exporter = provider()
    if exporter is None:
        return
    try:
        try:
            _write(exporter, job)
        except Exception:
            logger.exception("results export %s failed", job.id)  # the job id only, never a row
            try:
                exporter.fail(job.id, "error")
            except Exception:
                logger.exception("results export %s could not be marked failed", job.id)
        kick()
    finally:
        connection.close()  # last, so the claim in kick() leaves no connection open either
