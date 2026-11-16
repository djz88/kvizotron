# Test add-ons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass mark, a limit of N attempts with "more attempts after passing", kept score last/average, and reveal after the run closes, used by the quiz types; plus the deferred minors of project A.

**Architecture:** New settings are catalogue entries owned by the module that owns their neighbours (results plugin: pass mark, kept score; participants plugin: attempts; domain: reveal moment). Values that decide who may start and how a result counts are copied to the run (`PARTICIPANT_KEYS`, `RESULT_KEYS`); the reveal stays live (TD-101). One domain type `results.Kept` replaces "the official attempt" for every consumer, so average works everywhere.

**Tech Stack:** Django, Jinja2, HTMX, Pico, pytest; `make quality`.

**Spec:** `docs/superpowers/specs/2026-11-12-test-add-ons-design.md`

## Global Constraints

- Existing quizzes and runs do not change: every new setting defaults to today's behaviour (`pass_mark` "0" = none, `max_attempts` "0" = no limit, `after_pass` "more"); a run whose stored JSON lacks a key reads the catalogue default (`participants.rules_of`, `results.of` already do).
- "Forbid" keeps today's behaviour exactly, including `unfinished_attempt=submitted` → `replace`. Every row of `START_TABLE` in `tests/contracts/participant_policy.py` stays and passes unchanged.
- Admin strings cs + en; participant-facing strings cs, en, uk; plugin catalogues cs + uk. The word round/kolo/раунд is never used. Counts are written without plural forms ("Attempts left: 2", "Zbývající pokusy: 2").
- Every admin POST has `{{ csrf_input }}`; no inline scripts or styles; works without JavaScript.
- Audit entries and logs carry no names, e-mails or answers.
- Scope of the three new settings global → quiz with `scope_reason` "It concerns the whole attempt, so a question has no use for it." (copy the wording of `ATTEMPT_LIMIT`).
- Pass mark is in percent of the maximum score, 0–100, as string choices "0".."100" (manifest settings accept choices only, `app/kernel/manifest.py:14`).
- Changes to `app/contracts/`, `manifest.py` files and the participant policy are VELKÁ by the project profile; `CONTRACT_VERSION` becomes "1.1" (manifests declare `>=1.0,<2.0`).
- Commit messages end with the attribution lines from the session's system reminder.

## Review Focus

1. An old run (stored `participant_rules_json` / `results_json` without the new keys) must behave as today: no limit, no pass mark, kept score as stored. → Task 1 test `test_old_run_reads_defaults`.
2. Forbid with `unfinished_attempt=submitted` keeps restarting as today, while `allow` + limit 2 refuses a third start even when the first two were abandoned. → Task 4 contract rows.
3. Average with an attempt waiting for photo grading: kept score is "waiting", not a mark computed without it. → Task 2 test `test_kept_waits_for_grading`.
4. Automatic opening of a planned run (`run_schedule._open_due`, no request) is refused and audited when the quiz reveals after close and the run's profile is `score`. → Task 5 test `test_open_due_refuses_after_close_with_score_profile`.
5. A regrade that raises an attempt's score flips that attempt's mark and the participant's mark, nothing else (no stored flag). → Task 3 test `test_regrade_changes_mark`.

## Rulings made while planning (code facts the spec did not know)

- **No "existing grace".** A run closed at its deadline still accepts a photo submission whose upload started in time for `LATE_PHOTO_WINDOW` (10 min, `app/api/play.py:57`, `accepts_upload`). Answers after close are therefore shown from `closed_at + 10 min`; the constant moves to the domain as `attempts.LATE_UPLOAD_WINDOW` and `play.py` uses it. The note on the result names that moment ("from 12. 11. 18:10") when the run has a deadline. The spec line is corrected in Task 7.
- **Forbid unchanged** (see Global Constraints). The new counting applies only to `repeat_attempts=allow` with `max_attempts > 0`.
- **Average** = component means of the submitted attempts (score, max score), `correct` = floor of the mean (thresholds in correct answers are whole numbers, so `floor(mean) >= N` ⇔ `mean >= N`), `questions` = mean rounded half up; the representative attempt (for foreign keys, time on the scoreboard) is the last submitted one.
- **Per-attempt mark is computed**, never stored (regrading changes scores; no migration).
- **Test runs and preview** treat "after close" as "at end" (a test run never closes) and show the note.
- **Clash precedence**: after close with profile none/score yields one clash on `data_profile` (adjust → `answers`), never VISIBILITY.

---

### Task 0: Deferred minors of project A

**Files:**
- Modify: `app/domain/quiz_types.py` (`_plan`), `app/api/admin_forms.py` (`clash_message`), `app/api/admin_quizzes.py` (`_with_type`), `app/api/jinja2/admin/_setting_row.html`, `app/api/jinja2/admin/quiz_form.html`, `app/plugins/quiz_types/plugin.py` only if needed for the Protocol properties below, `app/contracts/__init__.py` (`QuizTypePlugin` attributes)
- Test: `tests/domain/test_quiz_types.py`, `tests/api/test_admin_quiz_types.py`, `tests/api/test_admin_quizzes.py` (or the file holding new-quiz tests), `tests/domain/test_setting_rules.py`, `tests/api/test_admin_forms.py` (or where `clash_message` is tested)

**Interfaces:**
- Produces: `_plan` never adjusts under `resets_all`; never adjusts a key in `new.values()`. `QuizTypePlugin.id/version/order/resets_all` declared as read-only `@property` in the Protocol.

- [ ] **Step 1: Write the failing tests**

```python
def test_basic_makes_no_adjustment(quiz_with_clashing_globals):  # globals: answers_visibility=participant, data_profile=score
    shown = quiz_types.preview(quiz, "basic")
    assert shown.adjusted == []

def test_adjustment_never_overwrites_the_types_own_key(made_up_type_setting_answers_visibility_participant_and_profile_score):
    shown = quiz_types.preview(quiz, "made_up")
    assert [c.reason for c in shown.refused] == ["visibility"]   # refused, not adjusted
    assert shown.adjusted == []

def test_several_clashes_keep_rule_order():          # FLOW before VISIBILITY before STATELESS
    assert [c.reason for c in setting_rules.clashes(values_with_three_clashes, None)] == [FLOW, VISIBILITY, STATELESS]

def test_deviations_skip_a_disabled_module(): ...   # key of a switched-off plugin is not a deviation
def test_two_modules_setting_the_same_key_fail_the_contract(): ...  # registry.owner_of duplicates → contract error

def test_unknown_clash_reason_names_it():
    with pytest.raises(KeyError, match="no_such_reason"):
        clash_message(Clash("no_such_reason", "k", None))

def test_new_quiz_with_a_disabled_type_says_so(client, disabled_quiz_types):
    response = client.post(NEW, {...valid..., "quiz_type": "practice"}, follow=True)
    assert "is no longer available" in response.content.decode()   # en; cs "už není k dispozici"
    assert Quiz.objects.get(slug=...).quiz_type == ""

def test_mark_described_by(client):
    html = settings_page_with_one_deviation()
    assert 'aria-describedby="mark-attempt_limit"' in html

def test_type_choice_legend_is_short(client):
    assert "<legend>Quiz type</legend>" in new_quiz_page()
```

and change `unique_ids` to `re.findall(r'(?<![\w-])id="([^"]+)"', html)` with a test that `data-id="x" id="x"` passes.

- [ ] **Step 2: Run them — Expected: FAIL** (`uv run pytest tests/domain/test_quiz_types.py tests/api/test_admin_quiz_types.py -q`)
- [ ] **Step 3: Implement.** Notice for the new-quiz redirect: the existing notice mechanism the settings page uses (query flag or messages, whichever the admin pages already use). Legend "Quiz type" / "Typ kvízu"; the old sentence becomes `<small>` under it.
- [ ] **Step 4: Run — Expected: PASS**; `make lint`.
- [ ] **Step 5: Commit** `fix(quiz-types): deferred minors — basic and own-key adjustments, aria mark, notices, tests`

---

### Task 1: New settings, copied to the run, number fields

**Files:**
- Modify: `app/contracts/__init__.py` (constants `PASS_MARK = "pass_mark"`, `MAX_ATTEMPTS = "max_attempts"`, `AFTER_PASS = "after_pass"`; add `PASS_MARK` to `RESULT_KEYS` (not to `RESULT_DISPLAY_KEYS`); add `MAX_ATTEMPTS`, `AFTER_PASS` to `PARTICIPANT_KEYS`; `CONTRACT_VERSION = "1.1"`)
- Modify: `app/plugins/results/manifest.py` (`pass_mark`; `official_attempt` choices + `last`, `average`), `app/plugins/participants/manifest.py` (`max_attempts`, `after_pass`; `unfinished_attempt` help), `app/domain/settings.py` (`RevealMoment.AFTER_CLOSE = "after_close"` with label)
- Modify: `app/api/admin_forms.py` (replace `_MinutesField` special cases by one `NumberChoiceField` for `NUMBER_KEYS`), `app/api/admin_view.py` (`CHILD_OF`)
- Test: `tests/contracts/test_results.py`, `tests/contracts/test_participants.py`, `tests/api/test_admin_settings*.py`, `tests/api/test_admin_runs.py`, `tests/domain/test_participants.py`, `tests/domain/test_results.py`

**Interfaces:**
- Produces: the keys above; `settings.resolve(PASS_MARK, quiz) -> "0".."100"`; `MAX_ATTEMPTS` choices "0".."20"; `AFTER_PASS` choices `more`, `stop`; `OFFICIAL_ATTEMPT` choices `best`, `first`, `last`, `average`; `REVEAL_MOMENT` choice `after_close`; `admin_forms.NUMBER_KEYS: Mapping[str, str]` key → unit label ("min", "%", "").
- Values and labels (en / cs):
  - `pass_mark`: "Pass mark (%)" / "Hranice úspěšnosti (%)", "0" → "No pass mark" / "Bez hranice"; group `playing`, level basic.
  - `max_attempts`: "At most attempts" / "Nejvýš pokusů", "0" → "No limit" / "Bez limitu"; group `participants`; `CHILD_OF["max_attempts"] = "repeat_attempts"`.
  - `after_pass`: "More attempts after passing" / "Další pokusy po splnění", `more` → "Allowed" / "Povoleny", `stop` → "Not after passing" / "Po splnění už ne"; group `participants`; `CHILD_OF["after_pass"] = "max_attempts"`.
  - `official_attempt`: `last` → "The last attempt" / "Poslední pokus", `average` → "The average of the attempts" / "Průměr pokusů".
  - `reveal_moment`: `after_close` → "After the run closes" / "Po uzavření běhu".
  - `unfinished_attempt` help: "Matters when an attempt may not be repeated or the number of attempts is limited." / cs equivalent.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_keys_resolve_to_defaults(quiz):
    assert settings.resolve(PASS_MARK, quiz) == "0"
    assert settings.resolve(MAX_ATTEMPTS, quiz) == "0"
    assert settings.resolve(AFTER_PASS, quiz) == "more"

def test_scopes_are_global_and_quiz():  # tests/contracts/test_settings_rule.py style
    for key in (PASS_MARK, MAX_ATTEMPTS, AFTER_PASS):
        assert settings.CATALOGUE[key].scopes == QUIZ_WIDE

def test_run_copies_new_keys(quiz):  # override pass_mark 70, max_attempts 2, after_pass stop, official average
    run = plan_run(quiz)
    assert results.of(run)[PASS_MARK] == "70"
    assert participants.rules_of(run)[MAX_ATTEMPTS] == "2"
    assert participants.rules_of(run)[AFTER_PASS] == "stop"

def test_old_run_reads_defaults(run_without_new_keys):
    assert results.of(run)[PASS_MARK] == "0"
    assert participants.rules_of(run)[MAX_ATTEMPTS] == "0"

def test_open_run_keeps_values_when_quiz_changes(open_run):
    settings.set_override(PASS_MARK, open_run.quiz, "50", admin_id=A)
    assert results.of(open_run)[PASS_MARK] == "70"

def test_quiz_form_number_fields(client, quiz):  # quiz settings page
    page = get_settings(quiz)
    assert 'name="pass_mark" type="number" min="0" max="100"' in page   # attribute order per Django widget
    post_settings(quiz, pass_mark="75", max_attempts="3")
    assert settings.resolve(PASS_MARK, quiz) == "75"
    assert post_settings(quiz, pass_mark="101").status_code == 400

def test_run_plan_edits_new_keys(client, planned_run): ...   # pass_mark, max_attempts, after_pass, official_attempt on the plan form
```

- [ ] **Step 2: Run — Expected: FAIL** (unknown keys)
- [ ] **Step 3: Implement.** `NumberChoiceField(IntegerField)` returns a string, `min_value=0`, `max_value=int(last choice)`, empty = global (same contract as `_MinutesField`); used by the global form, the quiz form and `RunPlanForm` (which builds fields for `PARTICIPANT_KEYS` / `RESULT_KEYS` at `admin_forms.py:438`). `setting_value_label` appends the unit from `NUMBER_KEYS`. `make messages`, fill cs/uk.
- [ ] **Step 4: Run — Expected: PASS**; `make test` (wiring and settings contract tests included).
- [ ] **Step 5: Commit** `feat(test-add-ons): pass mark, attempt limit and after-pass settings copied to the run`

---

### Task 2: Kept score (last, average) for every consumer

**Files:**
- Modify: `app/plugins/results/ranking.py` (`pick_official`), `app/domain/results.py` (`Kept`, `kept`, `official_attempt`), `app/domain/rewards.py` (`refresh`, `_reached`, `_figures`, manual and draw grants), `app/domain/draws.py` (`_eligible`), `app/domain/results_export.py` (`official` column), `docs/_architecture/adr/0063-kept-score.md` (new, MADR 4)
- Test: `tests/contracts/result_view.py`, `tests/domain/test_results.py`, `tests/domain/test_rewards.py`, `tests/domain/test_draws.py`, `tests/domain/test_results_export.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class Kept:
    attempt: Attempt          # the chosen one; for average the last submitted (foreign keys, time)
    figures: AttemptFigures   # what counts: rewards, draws, pass mark, scoreboard
    count: int                # submitted attempts it comes from
    rule: str                 # first, best, last, average
    waiting: bool             # an attempt it depends on is PENDING_GRADING

def kept(participant: Participant) -> Kept | None: ...   # None: no submitted attempt and none waiting
def official_attempt(participant: Participant) -> Attempt | None  # = kept(...).attempt, kept for callers outside this task
```

- `pick_official(entries, "last")` → latest `submitted_at` (tie: `attempt_id`); `"average"` → a new `ScoreEntry` with `attempt_id`, `submitted_at`, `duration_ms`, `key`, `name` of the latest entry, `score` = mean score, `max_score` = mean max (Decimal, quantized like scores today).
- `waiting`: first → the earliest finished attempt is pending; last → the latest finished is pending; best and average → any finished attempt is pending. A waiting `Kept` is used by nothing that grants or ranks: rewards, draws and pass judge it as "not yet" (rewards keep what they hold, as today when the official attempt is pending).
- Export `official` column: under average every submitted attempt of the participant is marked; otherwise the chosen one.

- [ ] **Step 1: Write the failing tests**

```python
# contract (tests/contracts/result_view.py)
def test_pick_last(self): assert self.view.pick_official([e(10, t=1), e(5, t=2)], "last").score == 5
def test_pick_average_is_a_new_entry(self):
    got = self.view.pick_official([e(10, max=20, t=1), e(6, max=10, t=2, id="b")], "average")
    assert (got.score, got.max_score, got.attempt_id) == (Decimal(8), Decimal(15), "b")

# domain
def test_kept_average_figures(participant_with_attempts_10of20_6of10):
    kept = results.kept(p)
    assert kept.figures == AttemptFigures(score=Decimal(8), max_score=Decimal(15), correct=..., questions=...)
    assert kept.attempt == last and kept.count == 2

def test_kept_correct_is_floor_of_mean(): ...      # correct 7 and 8 → 7
def test_kept_waits_for_grading(): ...             # average, one PENDING_GRADING → waiting True
def test_board_ranks_by_average(run_average): ...  # board row score == mean, time of the last attempt
def test_reward_threshold_on_average(): ...        # 80 % threshold: attempts 70 % and 90 % → granted, entitlement.attempt == last
def test_draw_minimum_on_average(): ...
def test_export_marks_all_attempts_under_average(): ...
def test_first_and_best_unchanged(): ...           # existing tests keep passing; add one asserting kept().attempt == old official_attempt()
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement.** `results.kept` builds entries as `official_attempt` does today (submitted, scored) plus a query for pending ones; rewards/draws use `kept.figures` instead of `_figures(attempt)`; grants store `attempt=kept.attempt`. Write ADR-0063 "Kept score: last and average" (status accepted; it extends ADR-0026 and ADR-0053: the official result may be an average, the entitlement points at the last attempt).
- [ ] **Step 4: Run — Expected: PASS**; `make test`.
- [ ] **Step 5: Commit** `feat(results): kept score last and average for scoreboard, rewards, draws and export (ADR-0063)`

---

### Task 3: Pass mark — judged and shown

**Files:**
- Modify: `app/domain/results.py` (`attempt_passed`, `kept_passed`), `app/domain/participants.py` (`AttemptRow.passed`), `app/domain/run_stats.py` (`RunStats.passed`, `RunStats.judged`), `app/domain/results_export.py` (columns), `app/domain/results.py` `BoardRow.passed`, `app/api/play.py` (result context), `app/api/public.py` (`/v/<token>`), `app/domain/preview.py` / `app/api/admin_preview.py` (same as play)
- Templates: `public/_result.html`, `public/result.html`, `public/_scoreboard_rows.html`, `admin/run.html` (attempts table, statistics, admin board)
- Test: `tests/domain/test_results.py`, `tests/domain/test_run_stats.py`, `tests/domain/test_results_export.py`, `tests/api/test_play*.py`, `tests/api/test_public_result*.py`, `tests/api/test_scoreboard*.py`, `tests/api/test_admin_runs.py`

**Interfaces:**
- Consumes: `results.kept`, `Kept` (Task 2); `PASS_MARK` copied in `results.of(run)` (Task 1).
- Produces:

```python
def pass_mark(run: QuizRun) -> Decimal | None: ...        # None when "0"
def attempt_passed(attempt: Attempt) -> bool | None: ...  # None: no pass mark, not submitted, pending, or max_score 0
def kept_passed(kept: Kept | None, run: QuizRun) -> bool | None: ...  # None also when kept.waiting
```

  `percent = score / max_score * 100`, passed when `percent >= mark` (Decimal, no rounding before compare).
- Copy (en / cs; uk through the catalogue): "Passed ✓ — %(percent)s %% (pass mark %(mark)s %%)" / "Splněno ✓ — …(hranice …)"; "Not passed — %(percent)s %% (pass mark %(mark)s %%)" / "Nesplněno — …"; "Waiting for grading" / "Čeká na hodnocení"; kept line "Kept score: %(percent)s %% (%(rule)s of %(count)s) — %(verdict)s" / "Platné skóre: … (%(rule)s z %(count)s) — …" with rule words best/first/last/average.
- Export columns: attempts file `passed` (`yes` / `no` / empty), participants file `kept_percent`, `passed`. Both numeric/text classification per `_NUMERIC` rules.
- Statistics: "Passed: %(passed)s of %(judged)s" / "Splnilo: … z …".
- Scoreboard: a ✓ with visually hidden text "passed" in the score cell when `BoardRow.passed` is True; nothing otherwise.

- [ ] **Step 1: Write the failing tests**

```python
def test_attempt_passed_against_run_mark(run_mark_70):
    assert results.attempt_passed(attempt(score=7, max=10)) is True
    assert results.attempt_passed(attempt(score=69, max=100)) is False
def test_no_mark_means_none(): assert results.attempt_passed(a) is None
def test_regrade_changes_mark(): ...              # pending → graded to 8/10 → True; kept_passed follows
def test_mark_survives_quiz_change(open_run): ...  # quiz pass_mark → 90; attempt_passed unchanged
def test_result_page_shows_attempt_and_kept_line(client): ...  # two attempts, best → both lines; one attempt → only the first
def test_result_without_mark_unchanged(client): ...           # no "pass mark" text anywhere
def test_private_link_shows_mark(client): ...
def test_attempts_table_column(client): ...
def test_stats_share(client): ...                  # "Passed: 1 of 2"
def test_export_columns(): ...
def test_scoreboard_mark(client): ...              # public board row has ✓ and hidden "passed"
def test_preview_shows_mark(client): ...
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement.** Templates read only context values the views compute; no rule in templates.
- [ ] **Step 4: Run — Expected: PASS**; `make test`; `make messages` with cs/uk filled.
- [ ] **Step 5: Commit** `feat(results): pass mark on the result, private link, attempts, statistics, export and scoreboard`

---

### Task 4: Attempt limit and "more attempts after passing"

**Files:**
- Modify: `app/contracts/__init__.py` (`ParticipantPolicyPlugin.on_start`), `app/plugins/participants/policy.py`, `app/domain/participants.py` (`begin`, `attempts_left`), `app/domain/data_policy.py` (`conflicts`: `max_attempts > 0` under `none`), `app/api/public.py` (`may_restart`, attempts left), `app/api/play.py` (`played_result`, messages), templates `public/quiz.html`, `public/_error.html`
- Test: `tests/contracts/participant_policy.py`, `tests/contracts/test_participants.py`, `tests/domain/test_participants.py`, `tests/domain/test_data_policy.py`, `tests/api/test_play*.py`, `tests/api/test_public*.py`

**Interfaces:**
- Consumes: `results.kept`, `kept_passed` (Tasks 2–3); `MAX_ATTEMPTS`, `AFTER_PASS` in `rules_of(run)` (Task 1).
- Produces:

```python
def on_start(self, rules: Mapping[str, str], *, finished: bool, used: int, passed: bool,
             open_attempt: OpenAttempt) -> StartDecision: ...
# used: the participant's started attempts other than the open one
#       (SUBMITTED, PENDING_GRADING, ABANDONED, and IN_PROGRESS other than the open one; SWITCHED never)
# passed: kept_passed(...) is True (False when None)

def attempts_left(run: QuizRun, participant: Participant | None) -> int | None: ...  # None: no limit
```

- Decision table for `allow` with `max_attempts = N > 0` (forbid and `allow` with 0 unchanged):

| passed and after_pass=stop | open attempt | unfinished_attempt | used vs N | decision |
|---|---|---|---|---|
| yes | any | any | any | played |
| no | none | – | used < N | new |
| no | none | – | used ≥ N | played |
| no | running / expired | continue | – | resume / time_up |
| no | running / expired | used or submitted | used + 1 < N | replace |
| no | running / expired | used or submitted | used + 1 ≥ N | played |

- `StartDecision` stays; the page tells the two `played` cases apart by `attempts_left == 0` versus a passed kept score: "You have used all %(count)s attempts." / "Využili jste všechny pokusy (%(count)s)." and "You have already passed." / "Test už máte splněný.", each with the kept result (score and mark) and the private link as today.
- Quiz page before start (and in the resume offer): "Attempts left: %(count)s" / "Zbývající pokusy: %(count)s" when a limit applies and the browser is known; `may_restart` is also true under a limit with attempts left.
- A test run ignores the limit (`rules_of` forces `allow`; also force `MAX_ATTEMPTS` "0" there).

- [ ] **Step 1: Write the failing tests**

```python
# tests/contracts/participant_policy.py: keep START_TABLE rows; pass used=0, passed=False for them. Add LIMIT_TABLE:
LIMIT_TABLE = [
    # (N, after_pass, passed, unfinished, used, open, decision)
    ("2", "more", False, "continue", 0, "none", "new"),
    ("2", "more", False, "continue", 2, "none", "played"),
    ("2", "more", False, "continue", 1, "running", "resume"),
    ("2", "more", False, "submitted", 0, "running", "replace"),
    ("2", "more", False, "submitted", 1, "running", "played"),
    ("2", "more", False, "used", 1, "expired", "played"),
    ("3", "stop", True, "continue", 1, "none", "played"),
    ("3", "more", True, "continue", 1, "none", "new"),
]
def test_forbid_submitted_still_restarts(self):   # explicit Review Focus 2
    assert self.policy.on_start({REPEAT_ATTEMPTS: "forbid", UNFINISHED_ATTEMPT: "submitted"}, finished=False, used=5, passed=False, open_attempt="running") == "replace"

# domain
def test_abandoned_attempts_count(run_limit_2): ...    # start, restart (abandon), restart → third refused
def test_switched_chain_counts_once(): ...
def test_pending_grading_does_not_stop_after_pass(): ...
def test_limit_with_profile_none_is_a_clash(): ...     # data_policy.conflicts includes "max_attempts"
def test_attempts_left_on_quiz_page(client): ...       # "Attempts left: 1"
def test_used_all_message_with_kept_result(client): ...
def test_already_passed_message(client): ...
def test_test_link_ignores_limit(client): ...
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement.** `participants.begin` counts `used` in the same transaction it already runs in; `passed` from `results.kept_passed(results.kept(participant), run)`. Message for `max_attempts` under profile none: "Nothing is kept, which does not go with a limit on attempts." (extend `conflict_messages`).
- [ ] **Step 4: Run — Expected: PASS**; `make test`.
- [ ] **Step 5: Commit** `feat(participants): limit of attempts and no more attempts after passing (contract 1.1)`

---

### Task 5: Reveal after the run closes

**Files:**
- Modify: `app/domain/attempts.py` (`LATE_UPLOAD_WINDOW`), `app/api/play.py` (use it; `_revealed`, result note), `app/domain/reveal.py` (`shown_from`, `is_shown`), `app/api/public.py` (`_own_answer`), `app/domain/setting_rules.py`, `app/domain/data_policy.py` (`ensure_run_allowed`), `app/api/admin_forms.py` (messages), `app/domain/preview.py` / `app/api/admin_preview.py`
- Templates: `public/_result.html`, `public/result.html`
- Test: `tests/domain/test_setting_rules.py`, `tests/domain/test_reveal.py`, `tests/domain/test_run_schedule.py`, `tests/domain/test_quiz_types.py`, `tests/api/test_play*.py`, `tests/api/test_public_result*.py`

**Interfaces:**
- Produces:

```python
LATE_UPLOAD_WINDOW = timedelta(minutes=10)                     # attempts.py; play.LATE_PHOTO_WINDOW removed
def shown_from(run: QuizRun) -> datetime | None: ...           # closed_at + window when CLOSED/ARCHIVED; deadline_at + window while a deadline is set; else None
def is_shown(attempt: Attempt, now: datetime) -> bool: ...     # moment after_close: test run True; else run CLOSED/ARCHIVED and now >= closed_at + window
# setting_rules reasons:
AFTER_CLOSE_PROFILE = "after_close_profile"        # key data_profile; ADJUSTABLE → {data_profile: "answers"}
AFTER_CLOSE_VISIBILITY = "after_close_visibility"  # key answers_visibility; ADJUSTABLE → {answers_visibility: "participant"}
RUN_PROFILE = "run_profile"                        # key reveal_moment; refused, not adjustable
```

- Rules in `clashes(values, quiz)`, evaluated **before** the early return at `setting_rules.py:96`:
  - moment `after_close` and profile `none`/`score` → AFTER_CLOSE_PROFILE, and VISIBILITY is not reported for that combination;
  - moment `after_close` and visibility `admins` → AFTER_CLOSE_VISIBILITY;
  - moment `after_close` and a live run (`_live_runs`) whose `data_policy.of(run)` profile is `none`/`score` → RUN_PROFILE.
- `data_policy.ensure_run_allowed` adds `"reveal_moment"` to its refusal when `settings.resolve(REVEAL_MOMENT, quiz) == "after_close"` and the run's profile is `none`/`score`; this reaches `plan`, `update_plan`, `_open_due` (audited by `_refuse_opening`), `start_now` and `authoring.open_run`.
- Messages (en / cs): "Answers shown after the run closes need the data profile Answers or Detailed." / "Odpovědi po uzavření běhu potřebují profil dat Odpovědi nebo Podrobně."; "Answers shown after the run closes need participants to see their answers." / "…potřebují, aby účastník viděl své odpovědi."; run: "A planned or open run keeps no answers, so it cannot show them after it closes." / cs equivalent.
- Result note: "You will see the correct answers at this link after the run closes." plus, when `shown_from` is known, " (from %(when)s)" / "Správné odpovědi uvidíte na tomto odkazu po uzavření běhu (od %(when)s)." in the run's time zone (`clock`).

- [ ] **Step 1: Write the failing tests**

```python
def test_after_close_with_score_profile_adjusts_profile():
    found = setting_rules.clashes({REVEAL_MOMENT: "after_close", DATA_PROFILE: "score", ANSWERS_VISIBILITY: "participant"}, None)
    assert [c.reason for c in found] == [AFTER_CLOSE_PROFILE]
def test_type_preview_score_admins_after_close():   # quiz_types._plan: profile → answers, visibility → participant, not refused
def test_live_run_with_score_refuses(quiz_with_open_run_score):
    assert RUN_PROFILE in reasons(setting_rules.clashes({REVEAL_MOMENT: "after_close"}, quiz))
def test_open_due_refuses_after_close_with_score_profile(): ...   # automatic open refused and audited
def test_plan_refuses(): ...
def test_result_after_submit_shows_no_answers_and_the_note(client): ...
def test_private_link_hides_until_window_passes(client, freezer): ...  # closed_at + 9 min: hidden; + 10 min: shown at reveal_level
def test_test_link_shows_at_end(client): ...
def test_preview_shows_at_end_with_note(client): ...
def test_check_endpoint_refuses_after_close(): ...   # /check stays after_each only
```

- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement.** `attempts.start` already freezes `moment` into `settings_json`; `_revealed` returns [] for `after_close` unless `is_shown`; `_own_answer` adds the reveal only when `is_shown`. `settings.flow` keeps `after_close` (no flow conflict).
- [ ] **Step 4: Run — Expected: PASS**; `make test`.
- [ ] **Step 5: Commit** `feat(reveal): answers after the run closes, with clash rules for profile, visibility and runs`

---

### Task 6: Quiz types use the add-ons

**Files:**
- Modify: `app/plugins/quiz_types/plugin.py`, its `locale/` (cs, uk), `tests/contracts/test_quiz_types.py`
- Test: `tests/contracts/test_quiz_types.py`, `tests/domain/test_quiz_types.py`

**Interfaces:**
- Consumes: keys of Task 1, `after_close` of Task 5.
- Values (exact):
  - `final_test` adds `pass_mark: "70"`.
  - `mock_test` adds `pass_mark: "70"`, `max_attempts: "0"`.
  - New `resit_exam`, order 25, "Exam with a resit" / "Zkouška s opravným pokusem", description en "An exam with a pass mark and a second attempt; the better one counts and answers are shown after the run closes." (cs/uk translated): `navigation_mode step_no_back`, `shuffle_questions on`, `shuffle_options on`, `attempt_limit "30"`, `repeat_attempts allow`, `max_attempts "2"`, `after_pass more`, `ask_name required`, `ask_when start`, `ask_email off`, `duplicate_names allow`, `scoreboard_visibility hidden`, `official_attempt best`, `pass_mark "70"`, `reveal_moment after_close`, `reveal_level explanations`, `data_profile answers`, `answers_visibility participant`, `show_sources off`.
  - Practice, Contest, Pub quiz, Basic unchanged.

- [ ] **Step 1: Write the failing tests:** exact-dict tests for `final_test`, `mock_test`, `resit_exam`; `test_seven_types_in_order` (renamed) with ids `practice, final_test, resit_exam, mock_test, contest, pub_quiz, basic`; cs label "Zkouška s opravným pokusem"; `quiz_types.preview(quiz, "resit_exam")` on a default quiz has no refused clash.
- [ ] **Step 2: Run — Expected: FAIL**
- [ ] **Step 3: Implement**; `make messages`, fill cs/uk.
- [ ] **Step 4: Run — Expected: PASS**
- [ ] **Step 5: Commit** `feat(quiz-types): exam with a resit; pass mark in final test and mock test`

---

### Task 7: Docs and browser check

**Files:**
- Modify: `docs/_architecture/acceptance-criteria.md` (AC-172 pass mark, AC-173 attempt limit and after-pass, AC-174 kept score last/average, AC-175 reveal after close; FR mapping per `docs/_architecture/README.md`), `docs/_architecture/README.md` (AC range), `docs/_architecture/modules/api-ui.md` ("Where things are set" rows), `docs/_architecture/modules/domain.md`, `docs/_architecture/plugins/` files of results, participants and quiz types, `docs/plugin-api.md` (contract 1.1, `on_start`), `docs/superpowers/specs/2026-11-12-test-add-ons-design.md` (grace line → `LATE_UPLOAD_WINDOW`), `CLAUDE.md`, `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, plugin `CLAUDE.md` files
- Test: `tests/test_docs.py` (via `make test`)

- [ ] **Step 1:** Write the ACs (each names its tests), update the docs above.
- [ ] **Step 2:** `make quality` — Expected: exit 0.
- [ ] **Step 3:** Browser check on the throwaway instance (`kvizotron-browser-walkthrough`): 1280 light cs, 390 dark uk, keyboard — new quiz with Exam with a resit, plan and open a run, two attempts (fail, pass), result lines, attempts left, used-all message, scoreboard mark, close the run, private link before and after the window (shorten by closing with `closed_at` in the past via the shell, never in the shared stack).
- [ ] **Step 4: Commit** `docs: test add-ons (AC-172–AC-175, ADR-0063)`
