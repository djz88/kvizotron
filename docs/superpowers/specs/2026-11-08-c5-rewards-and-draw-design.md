# C5 Rewards and draw: design

Status: approved by the user 2026-11-08. Marks: **[user]** decided by the user, **[docs]** already decided in `docs/_architecture`, **[call]** the author's call, open to correction.

## Why

A competition ends with prizes. Today the admin sees a scoreboard and an attempts table, and hands out prizes on paper: who reached 90 %, who was drawn from a hat. Organisers want the app to say who earned what, to tell the participant how to claim it, and to run a draw that can be shown and reviewed afterwards (`FR-36` to `FR-39`, ADR-0013).

## Goals

1. **Reward rules per run**: threshold, participation, manual and draw rewards (the direct entitlement of `FR-36` is both participation and manual **[user]**), each with a name, a description and claim instructions in the quiz languages (`FR-36`) **[docs]**.
2. **Entitlements** created by the server from the official attempt and shown to the participant with the claim instructions (`FR-36`) **[docs]**.
3. **A manual draw** after the run closes, over an eligible snapshot the admin sees first, with a CSPRNG and an append-only audit (`FR-37`, `FR-38`, ADR-0013) **[docs]**.
4. **Alternates drawn at once** and an admin "move up" when a winner does not claim **[user]**; a substitute for one winner and a whole redraw, each with a reason **[user]**.
5. **Three settings** that decide where a run's rewards come from, how several thresholds combine and how winners are reached **[user]**.

## Non-goals

- Voucher codes or any automatic e-mail (`FR-36`, `FR-38`) **[docs]**.
- Deleting or pseudonymising draw data when retention ends: D3. C5 only stores data so that D3 can do it without touching draw metadata (`FR-39`) **[docs]**.
- Export of entitlements and draws: D2 **[docs]**.
- Rewards defined globally: a global reward list makes no sense **[user]**.
- Rewards across several runs or quizzes **[call]**.
- Verifiable public randomness (commit-reveal), rejected in ADR-0013 **[docs]**.

## Anti-goals

- A draw that starts by itself, or before the run is closed (`FR-37`) **[docs]**.
- An original draw record changed or deleted; every move-up, substitute and redraw is a new record (`FR-38`) **[docs]**.
- A test attempt, an abandoned or replaced attempt, or an attempt still waiting for grading in an entitlement or a draw (AC-12, AC-16) **[docs]**.
- An e-mail on any public page, in a draw log or in a log line **[docs]**.
- An entitlement taken back from someone who already received the prize **[call]**.
- Existing quizzes and runs change: without reward rules nothing new appears **[call]**.

## Behaviour

### Reward rules

A rule belongs to one run (`reward_rule.run_id`, data model) **[docs]**. Kinds (`FR-36`):

| Kind | Who gets it | Fields |
|---|---|---|
| Threshold | participant whose official attempt reaches the threshold, e.g. 3 of 5 correct or 80 % **[user]** | unit (percent, points or correct answers, `FR-36`, `FR-26`), value |
| Participation | every participant with a valid official attempt, at once **[user]** | none |
| Manual | participants the admin picks by hand on the run page, e.g. a jury prize **[user]** | none |
| Draw | winners of the draw for this rule | eligibility (everyone, or a minimum in percent or points), number of winners (≥ 1), number of alternates (≥ 0, default 2 **[call]**) |

Every rule has a name, a description and claim instructions per quiz language, the same per-language editing as quiz texts **[call]**. A run may have any number of rules, "none" is a run without rules **[docs]**.

- Thresholds compare exact values, never rounded ones; percent uses the attempt's full maximum including manual points (ADR-0033) **[docs]**. "Reaches" means `>=` **[call]**.
- Kind, unit, value, eligibility and counts are fixed once the run opens, like the participant rules; name, description and claim instructions stay editable, since they change only what is shown **[call]**.
- Rules are refused with the data profile `none` (AC-09, ADR-0012) and with answers after each question (ADR-0035, AC-18), with the same explanation pattern as the scoreboard **[docs]**.
- A run with any rule needs a participant row per browser, the same as a visible scoreboard (`needs_participant`, ADR-0051) **[call]**.

### Where a run's rules come from

New setting **Rewards of a new run**, values: from the previous run / from the quiz template / none; default none; scopes global and quiz; no run level, since it only fills the new run **[user]**. A global value only picks the source; it never holds rewards **[user]**.

- "From the previous run" copies the rules of the quiz's last normal run; if there is none, it falls back to the quiz template **[call]**.
- "From the quiz template" copies the quiz's template rules. The template is edited on a quiz tab "Rewards" under "More" **[call]**.
- The copy happens when the run is planned or opened, and the admin edits the run's own copy in the run plan **[call]**. A change of the template does not reach runs already planned **[call]**.

### Several thresholds

New setting **Several thresholds**, values: only the highest reached / all reached; default only the highest **[user]** (default **[call]**); inherited global → quiz, copied onto the run and editable in the plan like the scoreboard settings (global → quiz → run) **[user]**. Fixed once the run opens **[call]**. "Several thresholds" applies only to threshold rules; participation, manual and draw rules always add up **[call]**. Under "only the highest", thresholds are compared as a share of the attempt's own maximum (points / maximum points, correct answers / questions of the attempt), so mixed units still order **[call]**.

### Entitlements

- Created by the server in the same transaction as the submission, from the participant's official attempt (`results.official_attempt`, invariant 5 in contracts) **[docs]**. The participant's entitlements are recomputed when a later attempt becomes official or when grading of an attempt finishes **[call]**.
- An attempt still waiting for grading creates nothing until it is graded (ADR-0033) **[docs]**.
- Status: granted → handed over; or cancelled. The admin marks "handed over" and "cancelled" (with a reason) on the run page **[call]**. A recomputation that no longer qualifies cancels a granted entitlement automatically with the reason "no longer reached"; a handed-over one is never cancelled automatically **[call]**. Under "only the highest", a higher threshold cancels a lower granted one the same way **[call]**.
- Participation rewards: granted with the first valid official attempt; never cancelled by recomputation **[call]**.
- Manual rewards: the admin picks participants from the attempts table; they are granted at once and only the admin cancels them **[call]**.
- A participant may hold entitlements of several rules, and may win in several draw rules of one run **[call]**.
- Draw rewards: a winner's entitlement is created by the draw; alternates get none until moved up **[call]**.

### What the participant sees

The result page after submission and the private result link (`/v/<token>`) show each entitlement with its name, description and claim instructions, in the attempt's language **[user]** (option "result page"). A draw win appears there after the draw **[call]**. Nothing about rewards is shown before the participant submits **[call]**. The quiz start page may list the run's rewards by name and description (not the rules' internals) **[call]**.

### Reaching winners

New setting **Contacting winners**, values: warn when e-mail is not collected / the draw requires an e-mail / no warning; default warn **[user]**; inherited global → quiz → run like the scoreboard settings **[user]**.

- "Warn": the run plan shows a warning when the run has a draw rule and e-mail collection is off **[user]**.
- "Requires": a run with a draw rule cannot be planned or opened unless e-mail is "required" (participants setting `ask_email`) **[user]**.
- The admin sees the winner's nickname and e-mail (if collected) on the draw page; never anywhere public **[docs]**.

### The draw

On the draw page `/admin/runs/{id}/draw` (address already in `api-ui.md`) **[docs]**:

1. Available only when the run is closed (or archived) **[call]**, the data profile is not `none` and nothing waits for grading (AC-16) **[docs]**.
2. **Preview**: the eligible snapshot: participants with a valid official attempt, not test, filtered by the rule's minimum. The admin sees count and list before drawing (`preview_eligible()`, AC-12) **[docs]**.
3. **Draw**: the server rebuilds the snapshot, orders it deterministically by participant id, fingerprints it (SHA-256 of the ordered ids), and draws `winners + alternates` in order with `secrets.SystemRandom().sample` **[docs]** (algorithm name **[call]**). Winners are the first N; alternates are ranked 1..M **[user]**. If fewer are eligible than winners, it draws all of them and says so **[call]**.
4. **Audit** per draw record: time, admin id, run id, rule id and rules version, eligible count and fingerprint, selected ids in order, algorithm, reason for a repeat (`FR-38`) **[docs]**. Also written to `audit_event` and emitted as `draw.completed` (ADR-0016) **[docs]**.
5. **Publish winners**: a per-draw switch, off by default; when on, the public scoreboard page of the run lists the rule name and winners by nickname, or by the anonymous label when the nickname is missing **[call]**. Never an e-mail **[docs]**.

Later actions, each an appended record with the admin id, time and a required reason; nothing is overwritten **[user]**, **[docs]**:

- **Move up**: a winner did not claim. The first remaining alternate becomes a winner; the replaced winner's entitlement is cancelled with the reason **[user]**.
- **Substitute**: draw one new winner from the eligible snapshot minus everyone already drawn (winners and alternates) **[user]**. Offered when alternates run out, and also at any time **[call]**.
- **Redraw**: the whole draw again with a reason; the previous one stays in the history marked superseded and its granted entitlements are cancelled; handed-over ones stay **[user]**, **[call]**.

### Data

Tables as in `data-model.md`: `reward_rule`, `reward_entitlement`, `draw`, `draw_entry` **[docs]**. `draw_entry` keeps the participant id and a pseudonymous key (HMAC of the participant id with the server secret), so D3 can drop the participant link and keep the draw metadata (`FR-39`) **[call]**. The template rules of a quiz are rules with a quiz id and no run id, or a separate table; left to the builder.

### Where the code lives

Pure rules in two plugins with the contracts from `contracts.md`: `rewards` (`RewardPlugin`: which rules an official attempt meets, the tier choice) and `drawings` (`DrawingPlugin`: snapshot order, fingerprint, selection). Storage, transactions and pages in the domain and API, the same split as `results.local` (ADR-0051) **[call]**. A new ADR records the tiers, alternates, move-up and this split **[call]**.

## Constraints

- Server computes everything; no client value decides an entitlement or a draw **[docs]**.
- Admin texts in cs and en, public texts in cs, en and uk **[docs]**.
- Every new setting has `group` and `level` (ADR-0052): all three in group `scoreboard`, level advanced **[call]**.
- About 50 concurrent participants on SQLite: the entitlement write must stay inside the submission transaction without extra round trips per rule **[docs]**.
- Plugins import only `app.contracts` **[docs]**.

## Risks

- Recomputing entitlements on grading and on a new official attempt is the place where a prize can silently move; covered by tests for each transition **[call]**.
- "Only the highest" with mixed units needs a percent comparison; a rule in points on a run with several revisions of different maximum compares against each attempt's own maximum **[call]**.
- The draw is auditable only at application level, not towards the DB admin (ADR-0013) **[docs]**.

## Left to the builder

- Exact page layout of the rules editor, the draw page and the entitlement list.
- Whether template rules share the `reward_rule` table.
- How the run page shows entitlements (own section or a column in the attempts table).
- Names of the setting keys and contract methods.

## Verification

- Contract tests for both plugins in `tests/contracts/`.
- Unit tests: thresholds at the exact boundary (AC-10: 4 of 5 = 80 % does not reach 90 %), mixed units, tiers vs all, recomputation on grading and on a better attempt, handed-over never cancelled.
- Draw tests: refused while open, under `none` and while grading is pending; test attempts excluded; same snapshot gives the same fingerprint; move-up, substitute and redraw append records and never change the original.
- New AC from AC-90: rules and entitlements, draw with alternates, repeat actions, contact setting.
- Browser walkthrough on `kvizotron-browser` with a new quiz `c5-…`: rules in the plan, result page with claim instructions in cs/en/uk, draw, move-up, published winners.
- `make quality`, `make smoke`.
