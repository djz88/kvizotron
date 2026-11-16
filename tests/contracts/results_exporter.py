"""Shared contract suite: every results exporter module must pass it (`delete_for_runs`)."""

import os
from typing import Any

import pytest

from app.contracts import ExportJobGone, ExportJobView, ExportTable, ResultsExporterProvider

QUIZ = "quiz-contract"
OTHER_QUIZ = "quiz-other"
RUN = "run-contract"
OTHER_RUN = "run-other"
GONE = "run_data_deleted"


class ResultsExporterSuite:
    def __init__(self, provider: object) -> None:
        assert isinstance(provider, ResultsExporterProvider)
        self.provider: ResultsExporterProvider = provider
        self._admins = 0

    def run(self) -> None:
        self.a_finished_export_naming_the_run_is_gone_with_its_files()
        self.a_finished_export_of_all_runs_of_the_quiz_is_gone_too()
        self.an_export_of_other_data_stays()
        self.a_waiting_export_ends_as_failed_with_its_reason()
        self.a_running_export_ends_as_failed_and_cannot_finish()
        self.deleting_again_changes_nothing_more()
        self.naming_no_run_changes_nothing()

    def _admin(self) -> str:
        self._admins += 1
        return f"contract-admin-{self._admins}"

    def _queued(self, admin: str, choices: dict[str, Any]) -> str:
        return self.provider.create(admin, {"quiz": QUIZ, "all_runs": False, "runs": [], **choices})

    def _done(self, admin: str, choices: dict[str, Any]) -> tuple[str, str]:
        """A finished export and the path of its file."""
        job_id = self._queued(admin, choices)
        claimed = self.provider.claim_next()
        assert claimed is not None and claimed.id == job_id
        table = ExportTable("attempts", ["run"], ["Run"], [{"run": "1"}])
        self.provider.write(job_id, [table], {}, False)
        view = self.provider.job(job_id, admin)
        assert view.status == "done" and view.files
        path = self.provider.path(job_id, admin, view.files[0])
        assert os.path.isfile(path)
        return job_id, path

    def _gone(self, job_id: str, admin: str, path: str) -> None:
        with pytest.raises(ExportJobGone):
            self.provider.job(job_id, admin)
        with pytest.raises(ExportJobGone):
            self.provider.path(job_id, admin, os.path.basename(path))
        assert job_id not in [view.id for view in self.provider.jobs(admin)]
        assert not os.path.exists(path)

    def _stays(self, job_id: str, admin: str, path: str) -> ExportJobView:
        view = self.provider.job(job_id, admin)
        assert view.status == "done"
        assert os.path.isfile(self.provider.path(job_id, admin, os.path.basename(path)))
        return view

    def a_finished_export_naming_the_run_is_gone_with_its_files(self) -> None:
        admin = self._admin()
        job_id, path = self._done(admin, {"runs": [RUN]})
        self.provider.delete_for_runs(QUIZ, [RUN])
        self._gone(job_id, admin, path)

    def a_finished_export_of_all_runs_of_the_quiz_is_gone_too(self) -> None:
        admin = self._admin()
        job_id, path = self._done(admin, {"all_runs": True})
        self.provider.delete_for_runs(QUIZ, [RUN])
        self._gone(job_id, admin, path)

    def an_export_of_other_data_stays(self) -> None:
        admin = self._admin()
        other_run, other_run_path = self._done(admin, {"runs": [OTHER_RUN]})
        other_quiz, other_quiz_path = self._done(
            admin, {"quiz": OTHER_QUIZ, "all_runs": True, "runs": [OTHER_RUN]}
        )
        self.provider.delete_for_runs(QUIZ, [RUN])
        self._stays(other_run, admin, other_run_path)
        self._stays(other_quiz, admin, other_quiz_path)

    def a_waiting_export_ends_as_failed_with_its_reason(self) -> None:
        admin = self._admin()
        job_id = self._queued(admin, {"runs": [RUN]})
        self.provider.delete_for_runs(QUIZ, [RUN])
        view = self.provider.job(job_id, admin)
        assert (view.status, view.error, list(view.files)) == ("failed", GONE, [])
        assert self.provider.claim_next() is None  # it does not start after all

    def a_running_export_ends_as_failed_and_cannot_finish(self) -> None:
        admin = self._admin()
        job_id = self._queued(admin, {"runs": [RUN]})
        claimed = self.provider.claim_next()
        assert claimed is not None and claimed.id == job_id
        self.provider.delete_for_runs(QUIZ, [RUN])
        view = self.provider.job(job_id, admin)
        assert (view.status, view.error) == ("failed", GONE)
        table = ExportTable("attempts", ["run"], ["Run"], [{"run": "1"}])
        self.provider.write(job_id, [table], {}, False)  # the worker was still writing
        view = self.provider.job(job_id, admin)
        assert (view.status, list(view.files)) == ("failed", [])

    def deleting_again_changes_nothing_more(self) -> None:
        admin = self._admin()
        job_id = self._queued(admin, {"runs": [RUN]})
        self.provider.delete_for_runs(QUIZ, [RUN])
        self.provider.delete_for_runs(QUIZ, [RUN])
        view = self.provider.job(job_id, admin)
        assert (view.status, view.error) == ("failed", GONE)

    def naming_no_run_changes_nothing(self) -> None:
        admin = self._admin()
        job_id, path = self._done(admin, {"all_runs": True})
        self.provider.delete_for_runs(QUIZ, [])
        self._stays(job_id, admin, path)
