# Combined scoreboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One scoreboard table by percent across a run's revisions by default, and a shared display-only scoreboard for several runs of a quiz.

**Architecture:** The revision mode gets a third value `percent` (new default) handled in `results._ranked_tables`; the per-run merge flag and page are removed and the mode becomes a run display setting. A nullable self foreign key `QuizRun.board_main` links member runs to a main run; `results` builds the main run's public board from all linked runs. No attempt, participant or reward moves.

**Tech Stack:** Django, Jinja2, HTMX, pytest; `make quality`, `make messages`.

**Spec:** `docs/superpowers/specs/2026-11-16-combined-scoreboards-design.md`

## Global Constraints

- Czech UI: QuizRun is "běh", never "kolo". Every new string through `_()`, cs and uk via `make messages`.
- The server computes all scores and percentages; nothing comes from the client.
- Published revisions stay immutable; no attempt, participant, entitlement or draw row changes runs.
- Settings inherit global → quiz (ADR-0042); follow the `kvizotron-add-setting` skill for the new value.
- `app/domain/models.py`, migrations and `app/contracts/__init__.py` are VELKÁ-tier in this project.
- Every behaviour change starts with a failing test; tests are never weakened.

## Review Focus

1. A run with revisions of maximum 10 and 12: a 9/12 (75 %) ranks below 8/10 (80 %) — test in Task 2.
2. A shared board where one member run uses `latest`: its older-revision attempts do not appear — test in Task 3.
3. A member run with grading pending: the main run's public board says results are pending — test in Task 3.
4. Unlinking a shared board immediately changes the cached public board — test in Task 3.
5. An anonymous row in a shared board shows the run number, so two "Player 3" are distinguishable — test in Task 3.

---

### Task 1: Decision records

**Files:**
- Create: `docs/_architecture/adr/0065-scoreboard-by-percent-and-shared-boards.md` (MADR 4, `status: accepted`, date 2026-11-16, "supersedes ADR-0008")
- Modify: `docs/_architecture/adr/0008-scoreboard-revision-modes-default-separate.md` (status `superseded by ADR-0065`), `docs/_architecture/adr/README.md` (index), `docs/_architecture/plugins/results.md` (`FR-30` text), `docs/_architecture/acceptance-criteria.md` (`AC-06` reworded; one new AC with the next free number for the shared board), `docs/_architecture/TECH_DEBT.md` (`make tech-debt-create title="Full merge of runs into one"` with the open questions from the spec)
- Test: `uv run pytest tests/test_docs.py -q`

- [ ] **Step 1:** Write ADR-0065 from the spec: options considered (merge by points with equal maxima — the old rule; merge by percent; 1:1 by points — rejected by the user; full merge of runs — deferred), decision, consequences (AC-06 meaning changes; existing runs switch; rewards unaffected per TD-047).
- [ ] **Step 2:** AC-06 new text: "A run whose revisions have different maximum points shows one table ranked by percent by default; the admin can switch the run to one table per revision or only the latest revision." New AC: "Two or more runs of a quiz linked on the Runs page show one public table on the main run, ranked by percent; each run keeps its own data, rewards and own board; unlinking restores the main run's own board."
- [ ] **Step 3:** Run `uv run pytest tests/test_docs.py -q` → PASS; `make tech-debt-check` → PASS.
- [ ] **Step 4:** Commit `docs: ADR-0065 scoreboard by percent and shared boards`.

### Task 2: One table by percent inside a run

**Files:**
- Modify: `app/plugins/results/manifest.py` (`REVISION_MODE` choices `["percent", "separate", "latest"]`, default `"percent"`, label for `percent` "One table by percent"; help text no longer mentions merging on the run page)
- Modify: `app/contracts/__init__.py:110-114` (`RESULT_DISPLAY_KEYS` no longer excludes `REVISION_MODE`)
- Modify: `app/domain/results.py` (`revision_mode` drops `MERGED`; `_ranked_tables` handles `percent`; remove `MERGED`, `MergeRefused`, `merge`, `unmerge`, `_set_merged`)
- Modify: `app/api/admin_runs.py` (remove `run_merge`, `run_unmerge`, `_merge_context`, `_merge_refused`, `_merge_refusal`), `app/api/admin_urls.py` (remove the two routes), `app/api/jinja2/admin/run.html:68-78` (remove merge/unmerge block; the revision mode appears in the run's scoreboard form through `RESULT_DISPLAY_KEYS`), delete `app/api/jinja2/admin/run_merge.html`
- Create: `app/domain/migrations/0025_revision_mode_percent.py`
- Test: `tests/domain/test_results_board.py`, `tests/api/test_admin_runs.py`, `tests/domain/test_migration_0025.py` (pattern `test_migration_0024.py`); update tests that assert the merge page (find with `grep -rn "admin_run_merge\|results.merge\|MERGED" tests`) to the new behaviour, not weaker

**Interfaces:**
- Produces: `results.PERCENT = "percent"`; `_Ranked` for a percent table has `revision_id=None`, `revision_no=None`, `max_score=None`; `BoardRow.max_score` is the row's own revision maximum in every mode (template already prints `row.max_score`).

- [ ] **Step 1: Failing tests**

```python
def test_percent_table_ranks_by_share_of_own_maximum(run_with_two_revisions):
    # revision A max 10: attempt 8/10; revision B max 12: attempt 9/12
    board = results.board(run, audience="admin", locale="cs")
    assert len(board.tables) == 1
    assert [(r.score, r.max_score, r.percent) for r in board.tables[0].rows] == [(8, 10, 80), (9, 12, 75)]

def test_percent_is_the_default_for_a_new_run(...)  # of(run)[REVISION_MODE] == "percent"
def test_admin_can_switch_an_ended_run_to_separate_tables(admin_client, closed_run)  # run page form, 2 tables after
def test_merge_routes_are_gone(admin_client, run)  # reverse("admin_run_merge") raises NoReverseMatch
def test_migration_switches_separate_and_merged_runs_to_percent()  # separate→percent, merged on→percent and key dropped, latest stays, test runs untouched
```

- [ ] **Step 2:** Run `uv run pytest tests/domain/test_results_board.py tests/api/test_admin_runs.py tests/domain/test_migration_0025.py -q` → FAIL.
- [ ] **Step 3: Implement** — in `_ranked_tables`, `percent`: build `ScoreEntry` per attempt with its own `RunRevision.max_score`, rank on the percentage (scale each entry's score to `score / max * 100` as `Decimal` for ranking, keep the raw score and own max on the row); `_build` takes the row's maximum from the entry, not from the table. Migration 0025 `RunPython` over non-test runs' `results_json`, reverse no-op.
- [ ] **Step 4:** Focused tests PASS; `make messages` (commit only changed catalogs); `make lint`; `make test`.
- [ ] **Step 5:** Commit `feat(results): one scoreboard table by percent is the default`.

### Task 3: Shared board of several runs (domain)

**Files:**
- Modify: `app/domain/models.py` (`QuizRun.board_main = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="board_members")`)
- Create: `app/domain/migrations/0026_run_board_main.py`
- Modify: `app/domain/results.py`
- Test: `tests/domain/test_shared_board.py` (new)

**Interfaces:**
- Produces in `app/domain/results.py`:
  - `class ShareRefused(Exception)` with `code` in `{"too_few", "other_quiz", "test_run", "already_shared", "main_is_member"}`
  - `share_board(main: QuizRun, members: Sequence[QuizRun], *, admin_id: str) -> None` — `ensure_editable`, validate, set `board_main` on members in one transaction, audit `run.board_combined` (details: member run numbers), drop main's cache.
  - `split_board(main: QuizRun, *, admin_id: str) -> None` — clears members, audit `run.board_split`, drop cache.
  - `shared_runs(main: QuizRun) -> list[QuizRun]` — main plus members ordered by `run_no`; `[main]` when not shared.
  - `_forget(run)` also drops the cache of `run.board_main` when set.
- Consumes: `PERCENT` ranking from Task 2.

- [ ] **Step 1: Failing tests** — `test_shared_board_ranks_all_runs_by_percent`, `test_member_with_latest_mode_contributes_only_its_current_revision`, `test_pending_grading_in_a_member_holds_the_shared_board`, `test_anonymous_rows_show_the_run_number_when_shared` (label contains "Run 2"), `test_split_restores_the_main_board_at_once` (cache dropped), `test_share_refuses` parametrized over every `ShareRefused.code`, `test_archived_quiz_refuses_sharing`, `test_member_keeps_its_own_board`, `test_place_of_stays_within_the_own_run`, migration test for 0026.
- [ ] **Step 2:** Run `uv run pytest tests/domain/test_shared_board.py -q` → FAIL.
- [ ] **Step 3: Implement** — in `_build`, when `shared_runs(run)` has more than one run and audience is public or admin of the main run: candidates from each run filtered by that run's `revision_mode`, official attempt by each run's own rule (`_rank` grouping per run key), then one percent table ranked with the main run's tie rules; `_pending` is true if any linked run is pending; anonymous label gets the run number (new msgid "Run %(no)s · %(label)s", cs "Běh %(no)s · %(label)s").
- [ ] **Step 4:** Focused tests PASS; `make lint`; `make test`.
- [ ] **Step 5:** Commit `feat(results): shared scoreboard of several runs`.

### Task 4: Shared board in the admin and on the public page

**Files:**
- Modify: `app/api/admin_runs.py` (`runs_page` context gets each run's `board_main` and selectable runs; new views `board_share` and `board_split`, POST only, `@admin_required`, `@not_archived`, map `ShareRefused` codes to messages), `app/api/admin_urls.py` (`quizzes/<uuid:quiz_id>/board/share`, `runs/<uuid:run_id>/board/split`), `app/api/jinja2/admin/runs.html` (checkbox column "Run %(no)s to the shared scoreboard", radio "Run %(no)s as the main run", button "Save the shared scoreboard", per shared main a "Cancel the shared scoreboard" button), `app/api/jinja2/admin/run.html` (note "Shared scoreboard of runs 1, 2, 3" on the main run, "Part of the shared scoreboard of run N" on a member), `app/api/jinja2/public/scoreboard.html` (note naming the runs)
- Test: `tests/api/test_admin_runs.py`, `tests/api/test_scoreboard.py`; add both routes to the request-limit/CSRF route audit if `tests/api/test_request_limits.py` lists admin POST routes

- [ ] **Step 1: Failing tests** — share via the Runs page form → 302 and members linked; refusal codes show their Czech message with 200/409 as the page's other refusals do; split → board back to one run; public board of the main run lists rows of all linked runs and the note; member page note; archived quiz → 409.
- [ ] **Step 2:** Run the two test files → FAIL.
- [ ] **Step 3:** Implement views, templates, `make messages` (cs, uk).
- [ ] **Step 4:** Focused tests PASS; `make lint`; `make test`.
- [ ] **Step 5:** Commit `feat(admin): share one scoreboard across runs on the Runs page`.

### Task 5: Release checks

- [ ] **Step 1:** Browser walkthrough per `kvizotron-browser-walkthrough` on a throwaway stack: a run with two revisions of different maxima shows one percent table; switching to separate on the run page gives two tables; two runs shared on the Runs page show one public table at 390 px (uk, dark) and 1280 px (cs, light); split restores; `errs` empty.
- [ ] **Step 2:** `make quality` → exit 0.
- [ ] **Step 3:** Record any finding with `make tech-debt-create` or a new task; commit.

## Self-review notes

- Spec coverage: percent default and modes → Task 2; existing runs switch → Task 2 migration; shared board rules and behaviour → Tasks 3–4; full merge only recorded → Task 1 TECH_DEBT; docs → Task 1.
- Names used across tasks: `results.PERCENT`, `QuizRun.board_main`, `share_board`, `split_board`, `shared_runs`, `ShareRefused`.
- Decision made by the plan, not the user: the per-run merge page is removed and the revision mode becomes a run display setting, because with percent as default the page's only remaining job is switching one run's mode, which the run page's scoreboard form already does for the other display settings.
