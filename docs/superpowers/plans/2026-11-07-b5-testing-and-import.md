# B5 Preview, test links and CSV import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can click through any version of a quiz without storing anything, send colleagues test links that never count, and move questions in and out as CSV or ZIP.

**Architecture:** Preview builds an unsaved `Attempt` from a signed token and reuses the play templates. A test link is a hidden `QuizRun` of kind `test`; default managers hide test runs and test copies, so existing queries stay right without edits. CSV and ZIP live in a new `csv_io` provider that hands plain rows to the domain; each question type reads and writes its own columns through its contract.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, SQLite, stdlib `csv` and `zipfile`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-07-b5-testing-and-import-design.md`

## Global Constraints

- Branch `feat/b5-testing-and-import` from `main`. Nothing pushed; no remote.
- Every user-facing string goes through `gettext` with cs, en and uk translations (`make messages`). In UI, a `QuizRun` is běh/run; the word kolo never appears. Texts are not in the first person.
- Settings rule (ADR-0042): the `csv_io` manifest states `settings: []`. Limits are constants.
- Layers: `app/domain` never imports from `app/api`, `app/plugins` or `app/providers`; plugins read no settings.
- Tests never use the network. Fetches use the local fake from `tests/providers/test_media_remote.py` and `tests/api/test_external_images.py`.
- `kvizotron-browser` data is kept. Smoke on free ports: `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`.
- Limits: CSV 5 MB and 2000 rows; ZIP upload 100 MB, 500 entries, 200 MB unpacked; import job 24 h; fetch budget `FETCHES_SECONDS` of ADR-0043 (25 s); test token `secrets.token_urlsafe(32)`.
- Commits end with the attribution lines the session gives.

## Review Focus

Each has its test in the owning task.

1. A CSV saved by Excel: semicolons, BOM, CRLF, a quoted cell with a line break. It imports the same as a plain one (Task 5).
2. Double click on confirm: one import, and the second request shows the report (Task 8).
3. Import into a draft of a quiz with an open run: public quiz unchanged, no run moves (Task 8).
4. A frozen test copy after its bank question was edited or deleted: the link still plays what was frozen (Task 2).
5. A ZIP entry named `../../etc/x.png` or with an absolute path: nothing written, name only compared with cells (Task 5).

---

### Task 1: Run kinds, and tests that a test run stays invisible

**Files:**
- Modify: `app/domain/models.py`, `app/domain/usage.py`, `app/domain/quiz_state.py` only if a test demands it, `app/api/play.py:125`
- Create: migration in `app/domain/migrations/`
- Test: `tests/domain/test_run_kinds.py`

**Interfaces:**
- Produces: `QuizRun.Kind` (`NORMAL`, `TEST`), `QuizRun.kind`, `run_no` nullable; `QuizRun.objects` returns normal runs only, `QuizRun.all_kinds` returns all. `QuizRevision.Status.TEST_COPY`, `revision_no` nullable; `QuizRevision.objects` hides test copies, `QuizRevision.all_kinds` returns all. Model `RunTestLink` (`id` uuid7, `run` OneToOne to `QuizRun` related name `test_link`, `token` unique, `expires_at` nullable, `created_by` string, `created_at`), db table `test_link`.

- [ ] **Step 1: Write failing tests** with helper `make_test_run(quiz, revision)` in the test file, creating a run of kind `test` with its `RunRevision` row through `QuizRun.all_kinds`:

```python
def test_two_active_test_runs_and_a_normal_run_can_coexist(): ...
def test_test_run_takes_no_run_number_and_next_run_is_still_one(): ...   # authoring.open_run → run_no == 1
def test_quiz_state_ignores_test_run():                                  # state equals that of a quiz without one
    ...
def test_public_quiz_page_and_landing_never_show_a_test_run(client): ... # 'not running', not on landing
def test_public_run_address_refuses_a_test_run(client): ...              # /q/<slug>/r/<id> → does not exist
def test_admin_run_page_404s_and_run_list_omits_a_test_run(logged_in): ...
def test_publish_moves_no_test_run(): ...                                # current_revision unchanged, no new row
def test_usage_counts_a_test_run_as_needing_its_modules(): ...           # reason names the quiz
def test_test_copy_is_hidden_from_revision_list_and_latest_published(): ...
def test_language_lock_ignores_a_test_copy():                            # admin_forms.py:185
    ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_run_kinds.py -q`. Expected: FAIL, `QuizRun` has no `Kind`.

- [ ] **Step 3: Implement the models.** `one_open_run_per_quiz` and `run_no_per_quiz` gain `condition` `kind="normal"`. Declare `objects` first, with a manager filtering `kind=normal`, then `all_kinds = models.Manager()`; related managers use it through `_default_manager`, and foreign key access through the plain base manager keeps working. Same pattern on `QuizRevision`, excluding `TEST_COPY`. `QuizRevision.save` already guards non-drafts through `objects`: make it look through `all_kinds`. Also: `play.start` looks up through `all_kinds`; `usage._open_questions` too, with the reason text naming a test link when `run_no` is None.

- [ ] **Step 4: Run:** `uv run pytest tests/domain/test_run_kinds.py tests/domain tests/api -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: test runs and test copies that existing queries never see`

### Task 2: Test link lifecycle in the domain

**Files:**
- Create: `app/domain/run_links.py`
- Modify: `app/domain/attempts.py`, `app/domain/authoring.py`
- Test: `tests/domain/test_run_links.py`

**Interfaces:**
- Consumes: Task 1 models.
- Produces, in `run_links`:
  - `create(quiz, revision: QuizRevision | None, *, expires_at: datetime | None, admin_id: str) -> RunTestLink` (`None` means the draft; raises `authoring.PublicationError` when it fails the check; `ArchivedQuiz` behaviour as `_ensure_editable`)
  - `find_playable(token: str) -> RunTestLink | None`
  - `is_playable(link, now: datetime) -> bool`: run open, not past `expires_at`, quiz not archived
  - `cancel(link, *, admin_id)`, `delete(link, *, admin_id)`, `delete_attempts(link, *, admin_id)`
- Produces, in `authoring`: `freeze_copy(quiz) -> QuizRevision`: new revision, status `TEST_COPY`, `revision_no=None`, deep copy of `editable_questions`, passed through `_freeze`, after `validate_for_publication`. The draft is not touched.
- Produces, in `attempts`: error code `test_link_ended`, raised by `start`, `check`, and `_check_still_valid`, for a run of kind `test` when `run_links.is_playable` is false. Import inside the function if a cycle appears, as a last resort; prefer `is_playable` taking values and living beside the check.

- [ ] **Step 1: Write failing tests:**

```python
def test_link_on_a_published_revision_plays_it_through_attempts_start(): ...
def test_later_publish_and_draft_edit_leave_link_version_unchanged(): ...
def test_draft_copy_does_not_change_the_draft_and_keeps_its_content_after_edits(): ...
def test_copy_survives_bank_question_edit_and_delete(): ...             # Review Focus 4
def test_draft_failing_publication_check_raises_with_problems(): ...
def test_links_each_get_own_run_and_token(): ...                   # token length ≥ 43
def test_expired_link_refuses_start_submit_and_check():                  # code test_link_ended
    ...
def test_cancelled_link_refuses_submit_from_an_open_page_and_keeps_attempts(): ...
def test_archived_quiz_stops_its_links_and_restore_resumes_them(): ...
def test_delete_removes_link_attempts_rows_and_copy_and_nothing_else(): ...
def test_delete_keeps_a_published_revision(): ...
def test_delete_attempts_keeps_the_link_playable(): ...
def test_each_change_is_audited_without_the_token(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_run_links.py -q`. Expected: FAIL, no module `run_links`.

- [ ] **Step 3: Implement.** Create a `RunRevision` row like `open_run`, so `current_row` works. Audit actions `test_link.created`, `.cancelled`, `.deleted`, `.attempts_deleted`; details hold the link id, never the token. Delete order in one `atomic()`: attempts, revision rows, link, run, then the revision when its status is `TEST_COPY`. In `app/api/play.py` add `test_link_ended` to `STATUS` (410) and `MESSAGES`: `_("This test has ended.")`.

- [ ] **Step 4: Run:** `uv run pytest tests/domain -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: test links fixed to one version`

### Task 3: Test link pages

**Files:**
- Create: `app/api/admin_links.py`, `app/api/jinja2/admin/test_links.html`, `app/api/jinja2/public/_mode_bar.html`
- Modify: `app/api/public.py`, `app/api/urls.py`, `app/api/admin_urls.py`, `app/api/admin_workspace.py`, `app/api/jinja2/admin/_quiz_header.html`, `app/api/play.py`, `app/api/jinja2/public/_questions.html`, `_result.html`, `quiz.html`, `deploy/` docs if needed, catalogues
- Test: `tests/api/test_test_links.py`

**Interfaces:**
- Consumes: `run_links.*`.
- Produces: `/t/<str:token>` named `test_link`; admin `quizzes/<uuid>/tests` named `admin_quiz_tests` (tab key `tests`, label `_("Test links")`), `tests/<uuid>/cancel`, `/delete`, `/attempts/delete`. Partial `public/_mode_bar.html` takes `mode_bar` (`{"text": str, "links": [...]}`), also used by Task 4.

- [ ] **Step 1: Write failing tests:**

```python
def test_link_page_plays_to_a_result_without_login(client): ...
def test_every_step_says_it_is_a_test(client): ...                        # start page, questions, result
def test_invalid_cancelled_and_expired_links_give_one_same_message(client): ...  # identical body, status 200
def test_link_pages_carry_noindex_and_no_referrer(client): ...            # X-Robots-Tag, Referrer-Policy headers
def test_token_never_reaches_the_log(client, caplog): ...                 # any status, django.request included
def test_submit_after_cancel_from_open_page_shows_clear_message(client): ... # HTMX and plain form
def test_admin_form_lists_draft_published_and_older_not_a_test_copy(logged_in): ...
def test_draft_with_problems_is_refused_listing_them(logged_in): ...
def test_past_end_date_is_refused_keeping_the_form(logged_in): ...
def test_tab_lists_links_with_version_end_state_and_attempt_count(logged_in): ...
def test_tab_lists_attempts_with_score_duration_and_start(logged_in): ...
def test_tab_says_anyone_with_the_link_sees_the_questions(logged_in): ...
def test_cancel_delete_require_post_and_login(client, logged_in): ...
def test_quiz_with_an_active_link_looks_the_same_on_runs_page(logged_in): ... # AC-46
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_test_links.py -q`. Expected: FAIL with 404s.

- [ ] **Step 3: Implement.** `_unavailable` answers 404, and Django logs 4xx paths, so an ended link answers **200** with the same template, otherwise the token reaches the log. Set both headers on all `/t/` responses. Views in `play.py` add `mode_bar` when `attempt.run.kind == TEST`; `quiz.html` gets it too and hides the public-address parts. Attempts are listed through `link.run.attempts`. The end date is a `datetime-local` input read as UTC, as other admin times. Delete goes through `admin/confirm.html`, as other deletions. Check that `Dockerfile` (no `--access-logfile`) and `deploy/Caddyfile` (no `log`) record no paths, and write this into `docs/deployment.md` in Task 11; add `tests/test_layers.py`-style guard `test_deployment_logs_no_request_paths` reading both files in this task's test file.

- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/api tests/test_translations.py -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: admin page and public address for test links`

### Task 4: Preview

**Files:**
- Create: `app/domain/preview.py`, `app/api/admin_preview.py`
- Modify: `app/api/play.py` (extract what preview shares), `app/api/jinja2/public/_questions.html`, `_result.html`, `_reveal.html` if needed, `app/api/jinja2/admin/_actions.html`, `revisions.html`, `app/api/admin_urls.py`, catalogues
- Test: `tests/domain/test_preview.py`, `tests/api/test_preview.py`

**Interfaces:**
- Consumes: `selection.choose`, `attempts.questions_of`, `attempts.evaluate`, `attempts.option_seed_for`, `authoring.future_snapshot`, `authoring.validate_for_publication`, `_mode_bar.html`.
- Produces, in `preview`:
  - `start(quiz, revision: QuizRevision | None) -> Started(attempt: Attempt, token: str, problems: list[Problem])`; `None` means the draft
  - `load(token: str, quiz) -> Attempt`, raising `PreviewStale` when the signature fails, or the draft's `snapshot_hash` differs from the token's
  - `unusable(attempt, locale) -> dict[question_id, message]`: the question's `validate_definition` for that language
  - `score(attempt, answers) -> attempts.AttemptResult`: skips unusable questions, maximum summed from the given questions
- Attempt is **never saved**: `Attempt(run=QuizRun(quiz=quiz), revision=QuizRevision(snapshot_json=…), selection_json=…, settings_json=…)`. Token salt `kvizotron.preview`, contents: quiz id, revision number or none, snapshot hash, selection, flow.
- Routes: `quizzes/<uuid>/preview` (draft) and `quizzes/<uuid>/preview/<int:revision_no>`, GET renders fresh questions; `quizzes/<uuid>/preview/submit` and `/preview/check`, POST with CSRF. All `@admin_required`.

- [ ] **Step 1: Write failing tests:**

```python
# tests/api/test_preview.py
@pytest.mark.parametrize("navigation", ["all_at_once", "step", "step_back"])  # exact values from settings.Navigation
def test_clicking_through_stores_nothing(logged_in, navigation):
    before = row_counts()                     # every table from django.apps
    ...                                       # open, check a question, submit
    assert row_counts() == before and result_shown

def test_draft_and_older_revision_both_open(logged_in): ...
def test_refused_without_login(client): ...
def test_public_address_is_not_involved_and_no_run_needed(logged_in): ...
def test_draft_problems_listed_on_top(logged_in): ...
def test_question_lacking_this_language_says_so_and_rest_plays(logged_in): ...
def test_question_without_correct_answer_says_so_and_rest_plays(logged_in): ...
def test_empty_draft_points_to_editor(logged_in): ...
def test_draw_row_that_cannot_be_filled_is_a_problem_not_a_server_error(logged_in): ...
def test_draft_changed_under_open_preview_offers_restart(logged_in): ...
def test_each_opening_draws_anew(logged_in): ...
def test_bar_on_every_step_with_way_back(logged_in): ...
def test_reveal_follows_settings(logged_in): ...
def test_answer_key_absent_before_reveal_is_allowed(logged_in): ...
def test_tampered_token_is_refused(logged_in): ...
def test_submit_requires_csrf(): ...           # Client(enforce_csrf_checks=True)
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_preview.py tests/api/test_preview.py -q`. Expected: FAIL with 404s.

- [ ] **Step 3: Implement.** `_questions.html` takes optional `submit_url`, `check_url`, `poll` and `csrf`, defaulting to today's values, so the public page's output stays the same; preview sets `poll=False`. `_result.html` takes optional `back_url`. Reuse `_questions`, `_revealed`, `_answers` from `play.py`; an unusable question renders as a notice in its place, without calling the plugin. `selection.choose` behaviour on an unfillable row: read it, and turn its failure into a `Problem` through `validate_for_publication`. Nothing may call `get_draft`, as it writes.

- [ ] **Step 4: Run:** `make messages`, then `uv run pytest tests/domain tests/api -q`. Expected: PASS, including `tests/api/test_play*.py` unchanged.

- [ ] **Step 5: Commit:** `feat: preview a draft or revision without storing anything`

### Task 5: `csv_io` provider: reading and writing files

**Files:**
- Create: `app/providers/csv_io/{__init__,apps,manifest,models,provider,reader,writer}.py`, its migration
- Modify: `app/contracts/__init__.py`, `app/kernel/registry.py` (`PORTS`), `tools/messages.py`, `app/providers/CLAUDE.md`
- Test: `tests/providers/test_csv_reader.py`, `tests/providers/test_csv_writer.py`, `tests/contracts/test_csv_io.py`

**Interfaces:**
- Produces, in contracts:

```python
class ImportRefused(Exception): ...   # message for the admin; the whole file is unusable
class ImportJobGone(Exception): ...

@dataclass(frozen=True)
class CsvRow:
    number: int          # record number in the file, header is 1
    cells: Mapping[str, str]
    error: str | None    # too many cells

@dataclass(frozen=True)
class ParsedFile:
    columns: Sequence[str]
    rows: Sequence[CsvRow]
    files: frozenset[str]   # entry names, empty for a plain CSV

@dataclass(frozen=True)
class ImportJob:
    id: str
    target: Mapping[str, str]   # {"kind": "new_quiz" | "draft" | "bank", "id": str}
    mapping: Mapping[str, str]
    report: Mapping[str, Any] | None

@dataclass(frozen=True)
class ExportedFile:
    extension: str     # "csv" | "zip"
    content_type: str
    data: bytes

class ImporterProvider(Protocol):
    id: str
    def begin(self, admin_id: str, target: Mapping[str, str], chunks: Iterable[bytes]) -> str: ...
    def job(self, job_id: str, admin_id: str) -> ImportJob: ...        # ImportJobGone
    def read(self, job_id: str) -> ParsedFile: ...                     # ImportRefused
    def read_image(self, job_id: str, name: str) -> bytes: ...         # ImportRefused
    def set_mapping(self, job_id: str, mapping: Mapping[str, str]) -> None: ...
    def claim(self, job_id: str) -> bool: ...                          # False if already confirmed
    def finish(self, job_id: str, report: Mapping[str, Any]) -> None: ...  # stores report, removes file

class ExporterProvider(Protocol):
    id: str
    def write(
        self, columns: Sequence[str], rows: Sequence[Mapping[str, str]], files: Mapping[str, bytes]
    ) -> ExportedFile: ...
```

Capabilities `importer` and `exporter`, key `csv`. Manifest `settings: []`, `provides: ["importer", "exporter"]`. Model `ImportJobRecord` db table `import_job` per `data-model.md`, plus `target_json`, `mapping_json`. File at `Path(settings.KVZ_MEDIA_PATH) / "imports" / str(id)`: the media view only serves registered assets, so it is never served.

- [ ] **Step 1: Write failing tests:**

```python
def test_plain_csv(): ...
def test_excel_semicolons_bom_crlf_and_quoted_line_break_read_the_same(): ...   # Review Focus 1
def test_other_encoding_refused_saying_csv_utf8(): ...                          # cp1250 bytes
def test_header_only_lowercased_stripped_and_duplicate_refused(): ...
def test_row_with_too_many_cells_has_error_and_short_row_gets_blanks(): ...
def test_csv_over_5_mb_or_2000_rows_refused(): ...
def test_unbalanced_or_nul_input_refused_not_a_server_error(): ...
def test_protective_character_removed_on_read(): ...
def test_zip_reads_its_csv_and_lists_images(): ...
def test_zip_with_two_csvs_or_none_at_top_level_refused(): ...
def test_macos_metadata_entries_ignored(): ...                                  # __MACOSX/, .DS_Store
def test_not_a_zip_encrypted_or_corrupt_refused(): ...
def test_zip_over_entries_declared_size_or_upload_limit_refused_unread(): ...
def test_zip_lying_about_its_size_stops_at_the_limit(): ...
def test_zip_entry_with_traversal_name_writes_nothing_outside_job(): ...        # Review Focus 5
def test_new_upload_replaces_that_admins_job_not_another_admins(): ...
def test_expired_job_removed_on_next_begin_with_its_file(): ...
def test_job_of_other_admin_is_gone(): ...
def test_claim_is_true_once(): ...
def test_finish_removes_the_file_keeps_report(): ...
# writer
@pytest.mark.parametrize("text", ["=1+1", "+a", "-a", "@a", "\tx", "\rx", "'=1", "''+x", "'plain"])
def test_formula_protection_is_safe_and_lossless(text):
    cell = written_cell(text)
    assert cell[0] not in "=+-@\t\r"
    assert read_back(cell) == text
def test_no_files_gives_csv_with_bom_and_files_give_zip_with_csv_at_top(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/providers/test_csv_reader.py tests/providers/test_csv_writer.py tests/contracts/test_csv_io.py -q`. Expected: FAIL on import.

- [ ] **Step 3: Implement.** Writer: a cell matching `^'*[=+\-@\t\r]` gets one `'` in front. Reader: a cell matching `^'+[=+\-@\t\r]` loses one. Delimiter: whichever of `,` and `;` is more frequent in the header. `begin` writes chunks counting bytes, and stops at the limit. It tells CSV from ZIP by the `PK\x03\x04` start. Read entries with `ZipFile.open(...).read(limit + 1)`, and never call `extract`. Refuse flag bit 0 (encrypted). `csv.Error` becomes `ImportRefused`.

- [ ] **Step 4: Run:** the same tests, `tests/test_layers.py`, `tests/contracts/test_settings_rule.py`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: csv_io provider reading and writing CSV and ZIP`

### Task 6: Question types read and write their columns

**Files:**
- Modify: `app/contracts/__init__.py`, `app/plugins/questions/choice/plugin.py`, `app/plugins/questions/matching/plugin.py`, `tests/contracts/question_type.py`, `tests/contracts/demo_question_suite.py` and the demo plugin used by `tests/contracts/test_demo_question.py`, `tests/contracts/test_choice.py`, `test_matching.py`, `docs/plugin-api.md`
- Test: the shared suite

**Interfaces:**
- Produces, in `QuestionTypePlugin`:
  - `csv_columns(locales: Sequence[str]) -> Sequence[str]`
  - `from_csv(cells: Mapping[str, str], locales: Sequence[str]) -> JSON`, raising `CsvRowError(column: str | None, message: str)`, defined in contracts. Ids are generated.
  - `to_csv(config: JSON, locales: Sequence[str]) -> Mapping[str, str]`
- An image in a CSV-made definition is `{"asset": None, "source": <cell>, "alt": {...}}`: the plugin neither knows nor cares whether the cell is an address or a file name; Task 7 resolves it. `to_csv` writes `image.get("source", "")`.
- Choice columns: `prompt_<l>`, `kind`, `allow_multiple`, `reveal_count`, `option_N_<l>`, `correct`, `image`, `image_alt_<l>`, `option_N_image`, `option_N_image_alt_<l>`, with N from 1 to `MAX_OPTIONS`. `correct` is letters, `A`, `A,C`; numbers refused. A blank `allow_multiple` means true when more than one is correct, so a hand-written file needs no extra column; export always writes it.
- Matching columns: `prompt_<l>`, `config_json`: `{"mode", "direction", "items": [{"text": {...}, "match": {...}}]}`.

- [ ] **Step 1: Write failing shared tests** in `QuestionTypeContract`, with new class attribute `csv_bad_cells: list[dict]`:

```python
def test_csv_round_trip_keeps_the_content(self):
    cells = self.plugin.to_csv(self.definition, self.locales)
    again = self.plugin.from_csv(cells, self.locales)
    assert content_of(again) == content_of(self.definition)   # describe_definition values, ids left out

def test_csv_columns_cover_what_to_csv_writes(self): ...
def test_every_changed_definition_changes_the_csv(self): ...  # uses changed_definitions
def test_bad_cells_raise_csv_row_error(self): ...
def test_from_csv_generates_ids(self): ...
```

And in `test_choice.py`: letters `A,C`, a letter beyond the last option names column `correct`, numbers refused, 6 options, yes/no, images in question and option. In `test_matching.py`: pairs, ordering, invalid JSON names `config_json`.

- [ ] **Step 2: Run:** `uv run pytest tests/contracts -q`. Expected: FAIL, no `to_csv`.

- [ ] **Step 3: Implement** by building the form `parse_admin` already reads (`option_0_cs`, `correct_0`, `image_source`, `item_0_cs`…) and calling it, so duplicates and mismatches are refused the same way; `AdminFormError` becomes `CsvRowError(None, str(error))`.

- [ ] **Step 4: Run:** `make messages`, `uv run pytest tests/contracts tests/test_translations.py -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: question types read and write CSV columns`

### Task 7: Interpreting and applying an import in the domain

**Files:**
- Create: `app/domain/question_import.py`
- Test: `tests/domain/test_question_import.py`, `tests/fixtures/import/quiz-with-category.csv` (the 5 sample questions from `kv_z_17_listopad_st_tnost_a_evropa.md` in cs/en/uk, with `UA` as `uk`, and category columns)

**Interfaces:**
- Consumes: `ParsedFile`, plugin CSV methods, `settings.keys_for`, `settings.CATALOGUE`, `authoring.save_question`, `banks.save_question`, `settings.set_override`.
- Produces:

```python
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
    quiz: PlannedQuiz | None
    questions: list[PlannedQuestion]
    issues: list[Issue]
    unused_columns: list[str]
    refused: str | None      # whole file refused

@dataclass(frozen=True)
class Target:
    kind: str                # "new_quiz" | "draft" | "bank"
    quiz: Quiz | None
    bank: QuestionBank | None

def known_columns() -> set[str]: ...
def unknown_columns(columns: Sequence[str]) -> list[str]: ...
def interpret(parsed: ParsedFile, target: Target, mapping: Mapping[str, str],
              check_address: Callable[[str], None] | None) -> ImportPlan: ...
def apply(plan: ImportPlan, target: Target, *, admin_id: str) -> Outcome: ...
```

`Outcome(quiz, bank, added: int, issues)`. `check_address` is None when no media provider is enabled; an image cell is then a row error. Resolving images happens in Task 8, before `apply`, by replacing them inside `plan.questions`.

- [ ] **Step 1: Write failing tests:**

```python
def test_sample_with_category_plans_a_quiz_in_three_languages():
    plan = interpret(read("quiz-with-category.csv"), new_quiz, {"category_cs": "", ...}, check)
    assert len(plan.questions) == 5 and plan.quiz.locales == ["cs", "en", "uk"]
    assert "category_cs" in plan.unused_columns and not errors(plan)

@pytest.mark.parametrize("cells,column", [
    ({"type": "nonsense"}, "type"), ({"scoring": "nonsense"}, "scoring"),
    ({"prompt_cs": "", "prompt_en": "", "prompt_uk": ""}, None),
    ({"correct": "Z"}, "correct"), ({"points": "0"}, "points"), ({"points": "1.5"}, "points"),
    ({"setting_show_sources": "nonsense"}, "setting_show_sources"),
    ({"setting_navigation_mode": "step"}, "setting_navigation_mode"),      # quiz scope only
    ({"image": "http://example.test/a.png"}, "image"), ({"image": "missing.png"}, "image"),
])
def test_row_error_names_row_and_column_and_skips_row(cells, column): ...

def test_good_and_bad_rows_keep_good_ones(): ...
def test_missing_translation_no_correct_answer_and_no_alt_are_warnings(): ...
def test_text_in_a_language_the_target_lacks_is_dropped_and_reported(): ...
def test_address_and_file_are_told_apart(): ...
def test_image_cell_without_media_provider_is_a_row_error(): ...
def test_unknown_schema_version_refuses_file(): ...
def test_new_quiz_without_a_valid_quiz_row_refuses_file(): ...
def test_quiz_row_into_draft_or_bank_is_ignored_with_warning(): ...
def test_tags_into_quiz_and_points_into_bank_are_reported_as_unused(): ...
def test_mapping_renames_a_column_and_blank_means_do_not_use(): ...
def test_no_usable_row_creates_nothing(): ...
def test_apply_new_quiz_sets_fields_and_settings_and_nothing_is_published(): ...
def test_taken_slug_gets_a_number_with_warning(): ...
def test_apply_to_draft_adds_after_existing_questions(): ...
def test_apply_to_archived_quiz_refused(): ...
def test_apply_to_bank_sets_tags_and_incomplete_language_is_a_row_error(): ...
def test_html_in_a_cell_is_escaped_when_played(client): ...
def test_audit_records_counts_never_content(): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_question_import.py -q`. Expected: FAIL on import.

- [ ] **Step 3: Implement.** Common columns: `schema_version` (only `1`), `row_type` (`quiz`, or blank/`question`), `type`, `points`, `scoring`, `explanation_<l>`, `sources` (one per line), `tags` (comma separated), `setting_<key>`, and on the quiz row `slug`, `locales` (comma separated), `default_locale`, `title_<l>`, `description_<l>`. `l` is any of `settings.LANGUAGES`; other `_<xx>` columns count as unknown. New quiz: creation through what `quiz_new` calls; move `_free_slug` from `admin_quizzes.py` into the domain if the domain needs it. `apply` runs in one `atomic()`.

- [ ] **Step 4: Run:** `uv run pytest tests/domain/test_question_import.py tests/test_layers.py -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: interpret an import file and apply it to a quiz, draft or bank`

### Task 8: Import pages

**Files:**
- Create: `app/api/admin_import.py`, `app/api/jinja2/admin/import_upload.html`, `import_mapping.html`, `import_check.html`, `import_report.html`
- Modify: `app/api/admin_urls.py`, `app/api/jinja2/admin/quiz_list.html`, `quiz_edit.html`, `bank.html`, `deploy/Caddyfile`, catalogues
- Test: `tests/api/test_import.py`

**Interfaces:**
- Consumes: `ImporterProvider` through `registry`, `question_import.*`, `media_storage()`, `storage.fetch_image`, `storage.store_image`, `FETCHES_SECONDS`.
- Produces: routes `import/new` (`?target=new_quiz`, `draft:<id>`, `bank:<id>`), `import/<uuid>/mapping`, `import/<uuid>/check`, `import/<uuid>/confirm` (POST), `import/<uuid>/report`, all `@admin_required`.

- [ ] **Step 1: Write failing tests:**

```python
def test_clean_file_skips_mapping_and_nothing_changes_before_confirm(logged_in): ...
def test_unknown_column_opens_mapping_with_do_not_use_preselected(logged_in): ...
def test_check_lists_errors_with_row_and_column_and_shows_first_questions(logged_in): ...
def test_confirm_imports_good_rows_and_report_links_the_draft(logged_in): ...
def test_double_confirm_imports_once_and_second_shows_report(logged_in): ...         # Review Focus 2
def test_import_into_draft_of_running_quiz_leaves_public_quiz_unchanged(logged_in, client): ... # Review Focus 3
def test_publish_is_never_called_and_no_revision_is_published(logged_in): ...
def test_failed_address_keeps_question_warns_and_blocks_publish_in_copy_mode(logged_in, fake): ...
def test_internal_address_never_fetched_with_switch_off(logged_in, fake): ...
def test_fetches_share_the_25_s_budget_and_the_rest_counts_as_failed(logged_in, fake): ...
def test_fetching_happens_at_confirm_never_at_check(logged_in, fake): ...
def test_zip_image_is_stored_and_a_bad_one_is_a_row_error_in_the_report(logged_in): ...
def test_unconfirmed_import_stores_no_media(logged_in): ...
def test_refused_file_returns_to_upload_with_message(logged_in): ...
def test_expired_job_says_so(logged_in): ...
def test_other_admins_job_is_not_reachable(logged_in): ...
def test_buttons_hidden_and_pages_404_without_provider(logged_in): ...
def test_login_required_on_every_step(client): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/api/test_import.py -q`. Expected: FAIL with 404s.

- [ ] **Step 3: Implement.** Confirm: `claim` first; if False redirect to report. Outside any transaction, walk `questions.images_of` of each planned question: a cell that looks like an address is fetched under one deadline, failure leaves `asset: None` and adds a warning; a file name goes through `store_image(read_image(...))`, a refusal drops the row with an error. Cache by cell within one import. Then `apply`, then `finish` with a report: lists of issues, unused columns, counts, link target. The Caddyfile gets a larger `request_body` for `/admin/import/*`, 101 MB, and the 16 MB limit stays everywhere else. `admin_id` comes from the request, as in `quiz_new`. Measure a confirm with 500 small images in Docker in Task 11.

- [ ] **Step 4: Run:** `make messages`, `uv run pytest tests/api tests/domain tests/test_translations.py -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: import pages with mapping, check and report`

### Task 9: Export and round trip

**Files:**
- Create: `app/domain/question_export.py`, `app/api/admin_export.py`
- Modify: `app/api/admin_urls.py`, `quiz_edit.html`, `bank.html`, catalogues
- Test: `tests/domain/test_question_export.py`, `tests/integration/test_csv_round_trip.py`

**Interfaces:**
- Produces: `rows_for_quiz(quiz) -> ExportData`, `rows_for_bank(bank) -> ExportData`, with `ExportData(columns: list[str], rows: list[dict[str, str]], assets: dict[str, str], omitted_draws: bool)`, where `assets` maps a file name to an asset id. Routes `quizzes/<uuid>/export`, `banks/<uuid>/export`, GET, `@admin_required`; `Content-Disposition: attachment`.

- [ ] **Step 1: Write failing tests:**

```python
def test_round_trip_keeps_the_content_of_both_types_images_settings_and_formula_text(logged_in):
    quiz = rich_quiz()      # choice, yes/no, pairs, ordering, uploaded and address images,
                            # sources, explanation, question and quiz settings, a prompt "=1+1"
    imported = reimport(export(quiz))
    assert content_of(imported) == content_of(quiz)

def test_bank_round_trip_keeps_tags(logged_in): ...
def test_draft_preferred_then_published(): ...
def test_local_image_gives_zip_and_address_image_gives_only_the_address(logged_in): ...
def test_exported_cell_never_starts_with_a_formula_character(logged_in): ...
def test_quiz_with_draw_rows_says_on_page_they_are_left_out(logged_in): ...
def test_export_is_audited_and_requires_login(client, logged_in): ...
def test_imported_export_has_no_unused_columns_and_no_errors(logged_in): ...
```

- [ ] **Step 2: Run:** `uv run pytest tests/domain/test_question_export.py tests/integration/test_csv_round_trip.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement.** Work on a deep copy of the definition: an image with `asset` and no `source` gets `source = images/<asset id>.<ext from mime type>`, recorded in `assets`; then `plugin.to_csv` writes the cell. Bytes come from `storage.load(asset_id).path`. Columns are the union in a fixed order, common ones first. Points are not written for a bank question.

- [ ] **Step 4: Run:** `make messages`, `uv run pytest tests/domain tests/integration/test_csv_round_trip.py tests/api -q`. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: download a quiz or bank and import it back`

### Task 10: Sample and format description

**Files:**
- Create: `app/providers/csv_io/sample/quiz-sample.csv`, `app/providers/csv_io/sample/csv-format.md`
- Modify: `app/api/admin_import.py`, `import_upload.html`, `app/providers/csv_io/provider.py` if the path is exposed there
- Test: `tests/api/test_import.py`, `tests/providers/test_csv_sample.py`

**Interfaces:**
- Produces: routes `import/sample.csv`, `import/format.md`, `@admin_required`.

- [ ] **Step 1: Write failing tests:**

```python
def test_sample_imports_with_no_errors_no_warnings_and_no_mapping(logged_in): ...
def test_sample_holds_five_questions_in_three_languages_with_explanations_and_sources(): ...
def test_format_description_names_every_column_of_every_type_and_common_column(): ...
def test_upload_page_links_both(logged_in): ...
def test_fixture_with_category_reports_it_after_one_click(logged_in): ...           # AC-50
```

- [ ] **Step 2: Run:** `uv run pytest tests/providers/test_csv_sample.py tests/api/test_import.py -q`. Expected: FAIL.

- [ ] **Step 3: Create the files.** The sample is the fixture without category columns, with a quiz row. `csv-format.md` is in English, addressed to a person or an LLM writing the file: columns, `correct` letters, sources one per line, image cell rules, an example.

- [ ] **Step 4: Run:** the same. Expected: PASS.

- [ ] **Step 5: Commit:** `feat: sample CSV and a column description for writing one`

### Task 11: Documents and verification

**Files:**
- Create: `docs/_architecture/adr/0044-preview-and-test-links.md`, `0045-csv-one-file-and-failed-images.md`
- Modify: `docs/_architecture/adr/README.md`, `acceptance-criteria.md` (AC-45 to AC-52, as in the spec), `roadmap.md` (B5 done, D2 narrowed), `providers/csv-io.md`, `modules/domain.md`, `modules/contracts.md`, `data-model.md`, `security.md`, `docs/deployment.md`, `docs/plugin-api.md`, `README.md` map if needed, `CLAUDE.md`, `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, `app/plugins/CLAUDE.md`, `tests/CLAUDE.md` if needed

- [ ] **Step 1: Write the documents.** ADR-0044 refines ADR-0017 (a run's kind instead of a flag on each attempt). ADR-0045 refines ADR-0032 (quiz row in one file, question export in Stage B) and ADR-0043 (a failed fetch on import keeps the question). `app/domain/CLAUDE.md` says that `Attempt` queries across runs must filter on the run's kind, for C-stage work. `security.md` gets test links and ZIP limits; `docs/deployment.md` says nothing logs request paths and that keeping it so protects test tokens. Run `make tech-debt-create title="Question categories"`, and fill it: unused column on import today, could map to bank tags.

- [ ] **Step 2: Run:** `make quality`. Expected: lint, tests, gitleaks and tech-debt check pass.

- [ ] **Step 3: Run smoke:** `SMOKE_HTTP_PORT=18180 SMOKE_HTTPS_PORT=18543 make smoke`. Expected: all PASS.

- [ ] **Step 4: Verify in a browser on a rebuilt `kvizotron-browser`, on a new quiz, keeping its data:** preview on desktop and phone in light and dark; a link played in a private context, then cancelled with the page open; import of the sample and of a file with errors; a ZIP over 16 MB through Caddy; export and reimport; keyboard through mapping and the tab. Measure a confirm with 500 small images. If it takes over 60 s, lower the entry limit, and update the value in `csv-format.md`, `security.md` and the test.

- [ ] **Step 5: Commit:** `docs: milestone B5, preview, test links and CSV`
