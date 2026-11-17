# Deadline Submissions and the Counted Attempt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeated submission of the same attempt uses one place in the `submit` bucket (TD-091), and rewards, draws and the pass mark count the same attempt the scoreboard counts (TD-047).

**Architecture:** The in-memory limiter (`app/api/rate_limit.py`) gains a "count this attempt once per window" acquire used only by `submit`. `results.kept()` reuses the board's revision-mode filter and per-percent pick; a run-wide reward recomputation runs when the revision mode changes or the run switches revision.

**Tech Stack:** Django, pytest (`make test`).

**Spec:** `docs/superpowers/specs/2026-11-17-deadline-submit-and-official-attempt-design.md`

## Global Constraints

- No grace after the deadline (ADR-0025); `countdown.js` repeat schedule unchanged.
- `start`, `login`, `code`, `login_address` buckets unchanged; `submit` limit value, address key (`rate_limit.client_ip`) and 429 + `Retry-After` unchanged.
- A counted attempt is remembered 60 s (`rate_limit.WINDOW`) from its latest send and swept with the other idle keys (`_SWEEP_AT`).
- `results` stays the only owner of "which attempt counts"; `rewards` keeps calling `results.kept` / `results.official_attempt`.
- Revision modes (ADR-0065): `percent` and `separate` → the run's rule over all revisions by percent of each attempt's own revision maximum (`_pick_by_percent` with `_maxima(run)`); `latest` → only attempts of `run.current_revision`, by the run's rule. Within one revision behaviour is unchanged.
- `average`: picked as the board picks (mean of percents); the figures stay `_average_figures` (mean points over mean maxima).
- Recomputation follows ADR-0053: cancel only the run's own not-handed-over automatic threshold grants ("no longer reached"), never re-grant what an admin cancelled, never take back participation; draw history unchanged.
- No module-level import cycle (`tests/test_layers.py` green); limits stay in process memory (ADR-0058, ADR-0066).
- Docs in English; commits without a `Claude-Session` line; never touch Docker stacks `kvizotron-browser` or `kvizotron-tmp`.

## Review Focus

1. Parallel repeats of one attempt from 8 threads at the limit: exactly one place taken, all pass — Task 1 test.
2. Many different attempt ids from one address are still refused at the limit — Task 1 test.
3. A run that never switched revision ranks, rewards and judges the pass mark exactly as before — Task 2 (existing suites stay green, plus one explicit test).
4. `latest` mode: a participant with only old-revision attempts loses a not-handed-over automatic threshold grant, keeps participation and a handed-over grant — Task 3 test.
5. Test runs (`kind == TEST`) and shared boards (`board_main`) are unaffected — Task 2 and Task 3 tests.

---

### Task 1: One attempt, one place in the `submit` bucket (TD-091)

**Files:**
- Modify: `app/api/rate_limit.py` (new acquire, sweep, `reset`), `app/api/play_errors.py:114` (`_limited`), `app/api/play.py:628` (`submit`)
- Modify: `docs/_architecture/adr/0058-rate-limit-buckets.md` (addendum), `docs/configuration.md` (`KVZ_SUBMITS_PER_MINUTE` row wording), `docs/_architecture/TECH_DEBT.md` → resolve TD-091 with `make tech-debt-resolve id=TD-091` and a `- Resolution:` line in the archive
- Test: `tests/api/test_rate_limit.py`, `tests/api/test_request_limits.py` (or the existing submit-limit test file)

**Interfaces:**
- Produces: `rate_limit.try_acquire_once(bucket: str, key: str, token: str, now: float) -> bool` — True without taking a place when `(bucket, key, token)` was counted within `WINDOW` (refreshes its time); otherwise behaves like `try_acquire` and, on success, remembers the token. `_limited(request, bucket, token: str | None = None)`; `submit` passes `str(attempt_id)`.

- [ ] **Step 1: Failing tests** (limit set to 2 via `settings` override as existing limiter tests do):

```python
def test_a_repeat_of_the_same_attempt_counts_once():
    for _ in range(10):
        assert rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-a", now=100.0)
    assert rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-b", now=101.0)
    assert not rate_limit.try_acquire_once("submit", "1.2.3.4", "attempt-c", now=102.0)

def test_a_counted_attempt_is_forgotten_after_the_window():
    later = rate_limit.WINDOW + 2  # a (sent at 0) is forgotten, b (sent at 30) is still in the window
    assert rate_limit.try_acquire_once("submit", "k", "a", now=0.0)
    assert rate_limit.try_acquire_once("submit", "k", "b", now=30.0)
    assert rate_limit.try_acquire_once("submit", "k", "a", now=later)      # counts again: b + a = 2
    assert not rate_limit.try_acquire_once("submit", "k", "c", now=later + 1)  # bucket full

def test_parallel_repeats_take_one_place():  # 8 threads, same token, limit 1 → all True, one event stored

def test_submit_repeats_pass_the_limit(client):  # HTTP: limit 1; POST /a/<id>/submit twice with the same attempt → second is not 429; a second attempt id → 429 with Retry-After
```

- [ ] **Step 2: Run** `uv run pytest tests/api/test_rate_limit.py -q` — Expected: FAIL (no `try_acquire_once`).
- [ ] **Step 3: Implement** under the existing `_lock`; the token memory is swept with `_sweep` and cleared by `reset()`; `tracked()` keeps counting what bounds memory.
- [ ] **Step 4: Docs.** ADR-0058 addendum: `submit` counts each attempt once per window per address (a repeat of the same attempt passes), why (TD-091, ADR-0060 repeats at the deadline), and that different attempts still count. Configuration row: "Submitted attempts per client address per minute; a repeat of the same attempt counts once".
- [ ] **Step 5: Run** `make lint && make test` — Expected: PASS (including the 50-participant thread test in `tests/integration/test_concurrent_submissions.py`).
- [ ] **Step 6: Commit** `fix(limits): one place per attempt in the submit bucket (TD-091)`.

### Task 2: The counted attempt follows the board (TD-047)

**Files:**
- Modify: `app/domain/results.py` (`kept` l.452, reuse `_shown_candidates`/`_maxima`/`_pick_by_percent`)
- Test: `tests/domain/test_results_kept.py` (new) or the existing kept/official-attempt test module

**Interfaces:**
- Consumes: `results.revision_mode(run)`, `results._maxima(run)`, `results._pick_by_percent(attempts, maxima, rule)`.
- Produces: `results.kept(participant) -> Kept | None` with unchanged signature and `Kept` shape; `official_attempt` unchanged on top of it.

- [ ] **Step 1: Failing tests** (two revisions in one run: rev 1 max 10, rev 2 max 12; build them as the ADR-0065 tests do):

```python
def test_best_counts_by_percent_across_revisions():
    # A: rev1 8/10 = 80 %, B: rev2 9/12 = 75 %, rule best, mode percent
    assert results.kept(participant).attempt == attempt_a          # today: B (more points)

def test_separate_mode_counts_like_percent():                      # same data, mode separate → A

def test_latest_counts_only_the_current_revision():
    # mode latest, current revision rev2: participant with only a rev1 attempt → kept is None;
    # one with rev1 and rev2 attempts → their rev2 attempt

def test_one_revision_is_unchanged():                              # 2 attempts same revision, each rule → same as points order

def test_average_keeps_its_figures():                              # average over A and B: figures == _average_figures(...) as before

def test_a_test_run_and_a_shared_board_member_still_count():       # TEST run follows rules_for_quiz; member of board_main uses its own mode
```

- [ ] **Step 2: Run** the new tests — Expected: the percent/separate/latest tests FAIL.
- [ ] **Step 3: Implement** inside `kept` without duplicating `_pick_by_percent`; keep the `waiting` logic (ADR-0063) on the same filtered set.
- [ ] **Step 4: Run** `make test` — Expected: PASS (rewards, draw, pass-mark, export suites unchanged for single-revision runs).
- [ ] **Step 5: Commit** `fix(results): rewards and pass mark count the attempt the board counts (TD-047)`.

### Task 3: Recompute rewards when the counted attempt changes without a new attempt

**Files:**
- Modify: `app/domain/rewards.py` (new `refresh_run`), `app/domain/results.py` (`set_display` l.169, when `REVISION_MODE` changed), `app/domain/authoring.py` (`_move_round` l.513, after the switch)
- Modify: `docs/_architecture/adr/0053-*.md` (addendum answering its "Bad, because …" revision-mode line), resolve TD-047 with `make tech-debt-resolve id=TD-047` plus a `- Resolution:` line
- Test: `tests/domain/test_rewards_refresh_run.py` (new)

**Interfaces:**
- Produces: `rewards.refresh_run(run: QuizRun) -> None` — `refresh(participant)` for every participant of the run with a finished attempt, inside the caller's transaction; nothing for a test run.

- [ ] **Step 1: Failing tests:**

```python
def test_switching_to_latest_cancels_a_threshold_no_longer_reached():
    # threshold rule 70 %; participant P only on rev1 with 8/10 → granted (auto);
    # run switches to rev2, admin sets mode latest → P's grant cancelled, reason "no longer reached"

def test_participation_and_handed_over_grants_stay():              # same switch; participation and a handed_over threshold unchanged

def test_an_admin_cancelled_grant_is_not_granted_back():           # mode back to percent → still cancelled

def test_draw_history_is_unchanged_by_a_mode_change():             # a held draw's rows identical before/after

def test_a_revision_switch_recomputes():                           # `_move_round` with switch decision under latest → same effect as above
```

- [ ] **Step 2: Run** — Expected: FAIL (no recomputation).
- [ ] **Step 3: Implement** `refresh_run`; call it from `set_display` only when `revision_mode` changed, and from `_move_round` after a switch, in the same transaction, without a module-level import cycle (`tests/test_layers.py`).
- [ ] **Step 4: Docs.** ADR-0053 addendum: the official attempt follows the board's revision mode (ADR-0065), with the `latest` consequence and the recomputation on a mode change or revision switch.
- [ ] **Step 5: Run** `make lint && make test && uv run pytest tests/test_docs.py -q && make tech-debt-check` — Expected: PASS.
- [ ] **Step 6: Commit** `fix(rewards): recompute when the revision mode or revision changes (TD-047)`.
