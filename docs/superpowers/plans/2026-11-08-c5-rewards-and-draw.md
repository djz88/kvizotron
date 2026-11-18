# C5 Rewards and Draw Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A run can carry reward rules (threshold, participation, manual, draw) with texts in the quiz languages; the server grants entitlements from the official attempt and shows them with claim instructions; the admin runs a manual draw with alternates, move-up, substitute and redraw over an audited, append-only record.

**Architecture:** Two pure plugins behind new ports: `rewards.threshold` (`RewardPlugin`, port `reward`: which threshold rules an attempt reaches, tiers) and `drawings.manual` (`DrawingPlugin`, port `drawing`: snapshot order, fingerprint, CSPRNG selection). The rewards manifest declares the three settings. The domain owns the tables (`reward_rule`, `reward_entitlement`, `draw`, `draw_entry`), copies rules onto a run, grants entitlements inside the submission and grading transactions (`app/domain/rewards.py`) and runs draws (`app/domain/draws.py`), the same split as `results.local` (ADR-0051). The API adds a quiz tab with template rules, a run rewards page, a draw page and the participant-facing texts.

**Tech Stack:** Python 3.15, Django 6.1, Jinja2, HTMX, SQLite WAL, plain JS (no build), pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-c5-rewards-and-draw-design.md`

## Global Constraints

- Branch `feat/c5-rewards-and-draw`. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `make` needs uv 0.13+: `export PATH=<uv-0.13>/bin:$PATH`.
- Settings follow `kvizotron-add-setting`, group `scoreboard`, level `advanced`, constants in `app/contracts/__init__.py`:

  | Constant | Key | Values | Default | Scopes | On the run |
  |---|---|---|---|---|---|
  | `REWARD_SOURCE` | `reward_source` | `none`, `previous_run`, `quiz` | `none` | global, quiz | no (it only fills a new run) |
  | `REWARD_THRESHOLDS` | `reward_thresholds` | `highest`, `all` | `highest` | global, quiz | `QuizRun.rewards_json`, plan form, fixed once open |
  | `WINNER_CONTACT` | `winner_contact` | `warn`, `require_email`, `silent` | `warn` | global, quiz | `QuizRun.rewards_json`, plan form, fixed once open |

  Reason for scopes: "Applies to the whole run, not to one question." `REWARD_RUN_KEYS = (REWARD_THRESHOLDS, WINNER_CONTACT)`.
- Rule kinds `threshold`, `participation`, `manual`, `draw`; units `percent`, `points`, `correct`. Entitlement statuses `granted`, `handed_over`, `cancelled`; sources `auto`, `manual`, `draw`. Draw actions `draw`, `redraw`, `move_up`, `substitute`. Algorithm string `"secrets.SystemRandom.sample+sha256"`.
- Rule structure (kind, unit, value, minimum, winners, alternates) changes only while the run is `SCHEDULED`, or on the quiz template. Texts (`name`, `description`, `claim` per locale) change at any time. Winners ≥ 1, alternates 0–20, default 2; thresholds > 0; percent ≤ 100.
- Reached means `>=` on exact `Decimal`s. Percent and share use the attempt's own `max_score` (manual part included) and, for `correct`, the number of questions of the attempt (`len(attempts.items_of(attempt))`).
- Rules are refused with data profile `none`, with `reveal_moment == after_each` on the quiz, and, under `require_email`, when a draw rule exists and `ask_email != "required"`. Exception `rewards.RewardConflict(keys: list[str])`, messages: "Rewards need a data profile that keeps scores.", "Answers after each question cannot go with rewards.", "A draw needs a required e-mail under the chosen contact setting."
- Test runs never get rules, entitlements or draws. Abandoned, switched, replaced and pending attempts never count.
- No e-mail, participant id, attempt id or cookie value in public HTML, a log, an audit `details` or a URL. Audit `details` of a draw hold ids of draw entries' pseudonyms, never names or e-mails.
- The bank-row form already uses `admin/draw_form.html` and the word "draw" in `admin_banks.py`: name the new template `admin/prize_draw.html` and the module `app/api/admin_rewards.py`.
- Every public text in cs, en, uk, admin texts in cs and en, via `make messages`; revert `.mo` changes in untouched modules. A run is `běh` / `run`, never `kolo`.
- Phone width, light and dark, keyboard; no inline script (CSP).
- Plugins import only `app.contracts`. New ADR-0053, new AC from AC-90; each new AC and AC-09, AC-10, AC-12, AC-16, AC-18 is named by a test docstring (`tests/test_docs.py`). Migration `app/domain/migrations/0016_rewards.py`.

## Review Focus

1. A participant plays twice: 70 % then 92 % with tiers 70 % and 90 % under `highest`: the 70 % entitlement is cancelled ("no longer reached") unless already handed over, the 90 % one is granted. Tested in Task 3.
2. A photo attempt reaches the threshold only after grading, or loses it after a regrade: nothing before grading, granted after, cancelled when points drop (never when handed over). Tested in Task 3.
3. Draw when fewer are eligible than winners + alternates, or nobody: draws everybody in order, says how many; with nobody it refuses with a message and stores no record. Tested in Task 4.
4. Substitute after every eligible participant was already drawn: refused with a message, nothing stored. Tested in Task 4.
5. A rule name with `<b>` or a missing translation in uk: escaped, falls back to the quiz's default locale. Tested in Task 7.

---

### Task 1: Contracts and the two plugins

**Files:**
- Modify: `app/contracts/__init__.py` (three setting constants, `REWARD_RUN_KEYS`, dataclasses, two protocols, `PORTS["reward"]`, `PORTS["drawing"]`)
- Create: `app/plugins/rewards/{__init__,apps,manifest,thresholds}.py`, `CLAUDE.md`, `locale/`; `app/plugins/drawings/{__init__,apps,manifest,selection}.py`, `CLAUDE.md`, `locale/`
- Modify: `pyproject.toml` entry points `"rewards.threshold" = "app.plugins.rewards.manifest:MANIFEST"`, `"drawings.manual" = "app.plugins.drawings.manifest:MANIFEST"`; `tools/messages.py` `ROOTS`; `app/plugins/CLAUDE.md`
- Test: `tests/contracts/test_reward.py`, `tests/contracts/test_drawing.py`, `tests/plugins/test_reward_thresholds.py`, `tests/plugins/test_draw_selection.py`

**Interfaces:**
- `ThresholdRule(id: str, unit: str, value: Decimal)`, frozen.
- `AttemptFigures(score: Decimal, max_score: Decimal, correct: int, questions: int)`, frozen.
- `RewardPlugin`: `id`, `version`, `share(rule: ThresholdRule, figures: AttemptFigures) -> Decimal` (the threshold as a share 0–1 of that attempt; percent → value/100, points → value/max, correct → value/questions; max or questions 0 → share above 1, never reached), `reached(rule, figures) -> bool`, `qualifies(rules: Sequence[ThresholdRule], figures: AttemptFigures, mode: str) -> list[str]` (ids reached; under `highest` only the one with the largest share, ties by order in `rules`).
- `DrawingPlugin`: `id`, `version`, `algorithm: str`, `order(ids: Iterable[str]) -> list[str]` (sorted, unique), `fingerprint(ids: Iterable[str]) -> str` (sha256 hex of `"\n".join(order(ids))`), `select(ids: Iterable[str], count: int) -> list[str]` (`secrets.SystemRandom().sample(order(ids), min(count, n))`).
- Registered as `registry.register("reward", "threshold", ...)` and `("drawing", "manual", ...)`. Rewards manifest `settings` = the three settings; drawings manifest `settings: []`.

- [ ] **Step 1: Tests.** Contract tests: registered plugins satisfy the protocols; every manifest setting has scopes `["global", "quiz"]`, reason, `group == "scoreboard"`, `level == "advanced"`. `test_reward_thresholds.py` (docstring names `AC-10`, `AC-90`): `test_four_of_five_is_80_percent_and_misses_90`; `test_three_of_five_correct_reaches_3_correct`; `test_points_reach_on_equal`; `test_highest_returns_only_largest_share_of_mixed_units` (80 %, 7 points of max 10, 3 correct of 5 with figures 8/10, 4 of 5 → only the 80 % rule); `test_all_returns_every_reached`; `test_zero_max_never_reaches`. `test_draw_selection.py`: `test_fingerprint_ignores_input_order`; `test_select_returns_distinct_members_in_given_count`; `test_select_more_than_available_returns_all`; `test_select_uses_system_random` (monkeypatch `secrets.SystemRandom.sample`).
- [ ] **Step 2: Run** `uv run pytest tests/contracts/test_reward.py tests/contracts/test_drawing.py tests/plugins/test_reward_thresholds.py tests/plugins/test_draw_selection.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `make messages`.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rewards): reward and drawing contracts and plugins`.

### Task 2: Tables, copying rules onto a run, conflicts

**Files:**
- Modify: `app/domain/models.py`; Create: `app/domain/migrations/0016_rewards.py`
- Create: `app/domain/rewards.py` (rules part)
- Modify: `app/domain/authoring.py` (`open_run`), `app/domain/run_schedule.py` (`plan`, `update_plan`, `start_now` re-check), `app/domain/participants.py` (`needs_participant`), quiz settings refusal of `after_each` in `app/api/admin_forms.py`
- Test: `tests/domain/test_reward_rules.py`

**Interfaces:**
- Models (all `uuid7` ids):
  - `RewardRule`: `quiz` FK (PROTECT, `related_name="reward_rules"`), `run` FK null (CASCADE; null = quiz template), `position` int, `kind`, `threshold_unit` null, `threshold_value` Decimal(12,4) null, `min_unit` null, `min_value` null (draw eligibility, both null = everyone), `winners` int null, `alternates` int null, `texts_json` (`{locale: {"name", "description", "claim"}}`), `winners_public` bool False, `created_at`. Table `reward_rule`.
  - `RewardEntitlement`: `run` FK, `rule` FK (PROTECT), `participant` FK (CASCADE), `attempt` FK null (SET_NULL), `status`, `source`, `reason` (≤ 200), `created_at`, `changed_at` null, `changed_by` null. Unique (`rule`, `participant`) where status != `cancelled`. Table `reward_entitlement`.
  - `Draw`: `run` FK (PROTECT), `rule` FK (PROTECT), `action`, `parent` FK self null (the draw or redraw this action amends; a redraw points at the one it supersedes), `admin_id`, `created_at`, `eligible_count`, `eligible_set_hash`, `algorithm`, `rules_version` (sha256 of the rule's structure fields), `reason` (≤ 200, required except for `draw`), `audit_json`. Table `draw`. Never updated after insert.
  - `DrawEntry`: `draw` FK (CASCADE), `participant` FK null (SET_NULL), `pseudonym` (64, `salted_hmac("kvz-draw", participant_id).hexdigest()`), `position` int, `role` (`winner`, `alternate`, `out`). Table `draw_entry`.
  - `QuizRun.rewards_json = JSONField(default=dict)`.
- `rewards.of(run: QuizRun) -> dict[str, str]` (run values filled with defaults); `rewards.snapshot(quiz, chosen: Mapping[str, str] | None) -> dict[str, str]`.
- `rewards.copy_rules(run: QuizRun) -> None`: by `settings.resolve(REWARD_SOURCE, quiz=...)`: `previous_run` → rules of the quiz's latest other normal run (by `run_no`), else template; `quiz` → template; `none` → nothing. Copies structure and texts, `winners_public=False`. Never for a test run.
- `rewards.conflicts(run: QuizRun) -> list[str]` and `rewards.ensure_allowed(run) -> None` (raises `RewardConflict`) using the run's profile (`data_policy.of(run)`), the quiz's `reveal_moment`, `participants.rules_of(run)[ASK_EMAIL]`; keys: `"profile"`, `"reveal"`, `"contact"`.
- `open_run`, `plan`, `update_plan` take `rewards: Mapping[str, str] | None = None`, store the snapshot, call `copy_rules` (plan/open only) and `ensure_allowed` in the same transaction; `start_now` re-checks.
- `rewards.has_rules(run) -> bool`; `participants.needs_participant(run)` also returns True when it does.
- Rule editing: `rewards.save_rule(owner: Quiz | QuizRun, data: RuleData, *, rule: RewardRule | None, admin_id: str) -> RewardRule`, `rewards.delete_rule(rule, *, admin_id)`, `rewards.save_texts(rule, texts: Mapping[str, Mapping[str, str]], *, admin_id)`. `RuleData` dataclass with the structure fields and texts. Structure change on a run not `SCHEDULED` raises `rewards.RuleLocked`. Each audited (`reward.rule_saved`, `reward.rule_deleted`, `reward.texts_saved`) with rule id only.

- [ ] **Step 1: Tests** (`tests/domain/test_reward_rules.py`, docstring names `AC-09`, `AC-18`, `AC-90`, `AC-93`): `test_source_none_copies_nothing`; `test_source_quiz_copies_template`; `test_source_previous_run_copies_last_run_and_falls_back_to_template`; `test_template_change_does_not_reach_planned_run`; `test_test_run_gets_no_rules`; `test_rules_refused_with_profile_none`; `test_rules_refused_with_after_each`; `test_require_email_refuses_draw_without_required_email`; `test_warn_and_silent_allow_it`; `test_structure_locked_once_open_texts_editable`; `test_rules_make_participant_needed`; `test_quiz_after_each_refused_when_run_has_rules`; `test_migration_0016_leaves_runs_without_rules`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_reward_rules.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as in Interfaces; `make messages`.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rewards): reward rules on the run`.

### Task 3: Entitlements

**Files:**
- Modify: `app/domain/results.py` (public `official_attempt`), `app/domain/rewards.py`, `app/domain/attempts.py` (`_store`), `app/domain/grading.py` (`recalculated` callers or itself)
- Test: `tests/domain/test_entitlements.py`

**Interfaces:**
- `results.official_attempt(participant: Participant) -> Attempt | None`: the participant's `SUBMITTED` attempts with a score, through `pick_official` and the run's `OFFICIAL_ATTEMPT`.
- `rewards.refresh(participant: Participant) -> None`, called inside the transaction: in `_store` after the attempt row changes (when `attempt.participant` is set and the run is normal) and after `grading.recalculated`. Rules: participation → grant once an official attempt exists, never auto-cancel; threshold → `qualifies` on the official attempt's figures with `of(run)[REWARD_THRESHOLDS]`; grant missing, cancel granted ones no longer returned with reason `"no_longer_reached"`; never touch `handed_over`, `manual` or `draw` sources.
- `rewards.grant_manual(rule, participant, *, admin_id)`, `rewards.hand_over(entitlement, *, admin_id)`, `rewards.cancel(entitlement, reason: str, *, admin_id)` (reason required, ≤ 200). Audited without names.
- `rewards.of_participant(participant) -> list[RewardEntitlement]` (status not cancelled, ordered by rule position).

- [ ] **Step 1: Tests** (docstring names `AC-10`, `AC-16`, `AC-91`): `test_threshold_granted_in_submission_transaction`; `test_participation_granted_once`; `test_better_attempt_moves_tier_under_highest`; `test_all_mode_keeps_both`; `test_handed_over_never_cancelled_by_recompute`; `test_pending_photo_grants_nothing_until_graded`; `test_regrade_below_threshold_cancels_granted`; `test_first_official_attempt_ignores_later_better`; `test_manual_grant_hand_over_cancel_audited_without_names`; `test_test_run_attempt_grants_nothing`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_entitlements.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**; keep `refresh` to a fixed number of queries per call (rules of the run, the participant's attempts, the participant's entitlements).
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rewards): entitlements from the official attempt`.

### Task 4: The draw

**Files:**
- Create: `app/domain/draws.py`
- Test: `tests/domain/test_draws.py`

**Interfaces:**
- `draws.Eligible(participant_ids: list[str], fingerprint: str)`; `draws.preview(rule: RewardRule) -> Eligible`: participants of the run with an official attempt, filtered by the rule's minimum through the reward plugin (`reached`), ordered by the drawing plugin.
- `draws.DrawRefused(reason: str)` with reasons `run_not_closed` (status not `CLOSED`/`ARCHIVED`), `stateless`, `grading_pending` (`grading.waiting(run) > 0`), `not_a_draw_rule`, `nobody_eligible`, `nobody_left`, `no_alternate`, `already_drawn` (a `draw` exists; use redraw), `not_drawn`, `reason_missing`.
- `draws.Standing(draw: Draw | None, winners: list[DrawEntry], alternates: list[DrawEntry], history: list[Draw])`; `draws.standing(rule) -> Standing` replays the current chain (latest `draw`/`redraw` and its `move_up`/`substitute` children).
- `draws.draw(rule, *, admin_id) -> Draw`: rebuild snapshot, `select(ids, winners + alternates)`, first `winners` get role `winner` and a `draw` entitlement, rest `alternate` with positions 1..M.
- `draws.move_up(rule, winner: DrawEntry, reason: str, *, admin_id) -> Draw`: entry for the old winner role `out`, first remaining alternate becomes `winner`; cancel the old winner's `draw` entitlement unless handed over; grant the new one.
- `draws.substitute(rule, winner: DrawEntry, reason, *, admin_id) -> Draw`: select 1 from the snapshot minus everyone in the current chain.
- `draws.redraw(rule, reason, *, admin_id) -> Draw`: new chain with `parent` = superseded draw; cancel its granted `draw` entitlements with the reason; handed-over stay.
- `draws.set_public(rule, public: bool, *, admin_id)`: the only change of `RewardRule.winners_public`.
- Every action: one `Draw` row with `audit_json = {"selected": [pseudonyms in order], "count": n, "requested": k}`, `audit.record(action="draw.<action>", entity_type="run", ...)`, and `events.emit("draw.completed", {"run_id", "rule_id", "action"})`. All in one transaction.

- [ ] **Step 1: Tests** (docstring names `AC-12`, `AC-16`, `AC-92`): `test_refused_while_open_stateless_or_pending`; `test_test_attempts_never_eligible`; `test_preview_fingerprint_equals_draw_fingerprint`; `test_minimum_filters_eligible`; `test_winners_and_ordered_alternates`; `test_fewer_eligible_draws_everybody`; `test_nobody_eligible_stores_nothing`; `test_move_up_takes_first_alternate_and_keeps_original_rows`; `test_substitute_excludes_everyone_drawn`; `test_substitute_with_nobody_left_refused`; `test_redraw_supersedes_and_keeps_handed_over`; `test_reason_required_for_repeats`; `test_draw_rows_never_updated` (row values equal before and after later actions); `test_audit_has_pseudonyms_not_names`.
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_draws.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(draws): manual draw with alternates and append-only history`.

### Task 5: Admin rules: quiz template, run plan, run rewards page

**Files:**
- Create: `app/api/admin_rewards.py`, `app/api/jinja2/admin/rewards.html`, `admin/_reward_rule_form.html`
- Modify: `app/api/admin_forms.py` (`RewardRuleForm`; `RunPlanForm` fields for `REWARD_RUN_KEYS` with method `rewards() -> dict[str, str]`), `app/api/admin_runs.py` (pass `rewards=` to plan/open, `RewardConflict` messages), `app/api/admin_urls.py`, `admin/_quiz_header.html` (tab "Rewards" under "More"), `admin/run.html` (link and contact warning), `admin/run_plan.html`
- Test: `tests/api/test_admin_rewards.py`

**Interfaces:**
- Routes: `quizzes/<uuid:quiz_id>/rewards` `admin_quiz_rewards`; `runs/<uuid:run_id>/rewards` `admin_run_rewards`; POST `rewards/<uuid:rule_id>` `admin_reward_rule` (save, `action=delete`); POST `quizzes/<uuid:quiz_id>/rewards/new` `admin_quiz_reward_new`, `runs/<uuid:run_id>/rewards/new` `admin_run_reward_new`; POST `entitlements/<uuid:entitlement_id>` `admin_entitlement` (`action` ∈ `hand_over`, `cancel` with `reason`); POST `runs/<uuid:run_id>/rewards/grant` `admin_reward_grant` (rule, participant).
- `RewardRuleForm(locales: Sequence[str], structure_locked: bool)`: kind, unit, value, minimum unit and value, winners, alternates, and `name_<locale>` (required in the default locale, ≤ 80), `description_<locale>` (≤ 500), `claim_<locale>` (≤ 500). Locked fields disabled and ignored on POST.
- Run rewards page: rules with their texts, entitlements table (nickname or anonymous label, e-mail, rule, status, actions), manual grant form listing participants with a submitted attempt, warning "This run has a draw but does not collect e-mail." under `warn`.

- [ ] **Step 1: Tests** (docstring names `AC-90`, `AC-93`): `test_quiz_template_rule_created_and_listed`; `test_plan_copies_template_and_shows_rules`; `test_structure_fields_disabled_on_open_run_texts_saved`; `test_plan_form_sets_threshold_mode_and_contact`; `test_conflict_messages_shown_on_plan`; `test_contact_warning_shown_under_warn_only`; `test_hand_over_and_cancel_need_post_and_reason`; `test_manual_grant`; `test_pages_need_login`; `test_advanced_fields_shown_with_showing_all` (fixture `showing_all`).
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_rewards.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**; `make messages`.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rewards): admin pages for rules and entitlements`.

### Task 6: Admin draw page

**Files:**
- Modify: `app/api/admin_rewards.py`, `app/api/admin_urls.py`; Create: `app/api/jinja2/admin/prize_draw.html`
- Test: `tests/api/test_admin_draw.py`

**Interfaces:**
- GET `runs/<uuid:run_id>/draw` `admin_run_draw` (address from `api-ui.md`): one section per draw rule: refusal reason in words, or preview (count, fingerprint, nicknames), draw button; standing (winners with nickname and e-mail, alternates in order), history of every record with time, admin, action, reason, count, fingerprint, algorithm; actions move up / substitute (per winner, reason field) and redraw (reason field); publish switch.
- POST `runs/<uuid:run_id>/draw/<uuid:rule_id>` `admin_run_draw_action`, field `action` ∈ `draw`, `move_up`, `substitute`, `redraw`, `publish`, `unpublish`; `entry` for move-up and substitute; `DrawRefused` shown as a message with status 409.

- [ ] **Step 1: Tests** (docstring names `AC-12`, `AC-92`): `test_open_run_shows_refusal`; `test_preview_then_draw`; `test_move_up_substitute_redraw_through_page`; `test_reason_missing_rejected`; `test_history_lists_every_record`; `test_get_never_draws`; `test_publish_switch_audited`.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_admin_draw.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**; `make messages`.
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(draws): admin draw page`.

### Task 7: What the participant sees

**Files:**
- Modify: `app/domain/rewards.py` (`shown`), `app/api/play.py` (result context), `app/api/public.py` (private result and quiz page), `app/api/scoreboard.py` (winners), `public/_result.html`, `public/result.html`, `public/quiz.html`, `public/scoreboard.html`
- Test: `tests/api/test_public_rewards.py`

**Interfaces:**
- `rewards.ShownReward(name: str, description: str, claim: str, status: str)`; `rewards.shown(participant: Participant | None, locale: str) -> list[ShownReward]` (texts in `locale`, else the quiz default locale).
- `rewards.offered(run: QuizRun, locale: str) -> list[tuple[str, str]]`: name and description of each rule, for the quiz page.
- `rewards.public_winners(run: QuizRun, locale: str) -> list[tuple[str, list[str]]]`: rule name and winner names (nickname, else `results.anonymous_label` with the participant's board number) for rules with `winners_public`; shown on the scoreboard page even when the board itself is hidden.

- [ ] **Step 1: Tests** (docstring names `AC-91`): `test_result_page_shows_entitlement_with_claim_in_attempt_language`; `test_private_link_shows_draw_win_after_draw`; `test_nothing_shown_without_rules`; `test_missing_translation_falls_back_and_name_escaped`; `test_quiz_page_lists_rules_without_thresholds_internals`; `test_published_winners_on_scoreboard_without_email`; `test_unpublished_winners_absent`.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_public_rewards.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**; `make messages` (cs, en, uk).
- [ ] **Step 4: Run** these plus `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(rewards): rewards on result, quiz and scoreboard pages`.

### Task 8: Decision record and milestone documents

**Files:**
- Create: `docs/_architecture/adr/0053-rewards-tiers-alternates-and-draw-history.md` (accepted; tiers setting, participation and manual as the direct entitlement, alternates and move-up, append-only draw rows, structure fixed at open, plugin/domain split)
- Modify: `docs/_architecture/adr/README.md`, `roadmap.md` (C5 row, AC-90 to AC-93, `Done 2026-11-…`), `acceptance-criteria.md` (AC-90 to AC-93), `plugins/rewards.md`, `plugins/drawing.md`, `modules/contracts.md` (ports `reward`, `drawing`), `modules/api-ui.md` (addresses, "Where things are set"), `modules/domain.md`, `data-model.md` (columns as built), `docs/privacy.md`, `CLAUDE.md` (milestones, Status, "Next is D1"), `app/domain/CLAUDE.md`, `app/api/CLAUDE.md`, `app/plugins/CLAUDE.md`, `.claude/skills/kvizotron-check-integration/flows.md` (submission → entitlement, close → draw)
- Test: `tests/test_docs.py` (existing)

- [ ] **Step 1: Write** the ADR and AC rows; AC-90 rules and sources, AC-91 entitlements and what the participant sees, AC-92 draw with alternates and repeats, AC-93 contacting winners.
- [ ] **Step 2: Run** `make quality`. Expected: PASS.
- [ ] **Step 3: Commit** `docs: C5 rewards and draw`.
