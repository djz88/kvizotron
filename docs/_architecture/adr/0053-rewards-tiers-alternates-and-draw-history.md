---
status: accepted
date: 2026-11-08
---

# ADR-0053: Rewards copied onto the run, tiers by setting, alternates drawn at once, a draw history that only grows

## Context and Problem Statement

`FR-36` to `FR-39` ask for reward rules per run, entitlements the system stores, and a manual draw with an audit that is never overwritten. [ADR-0013](0013-manual-draw-csprng-append-only-audit.md) fixed that a draw is an admin command over a deterministic snapshot with a CSPRNG and an append-only record. Open were where a run's rules come from, what happens when one participant reaches several thresholds, what "direct entitlement" means, what an admin does when a winner does not claim, when an entitlement may be taken back, how the draw keeps its metadata once D3 drops the personal data, and which part is a plugin.

## Decision Drivers

* A prize never moves silently: a participant who holds it keeps it unless an admin says otherwise
* The server decides every entitlement and every draw; no client value counts
* Each draw action can be reviewed afterwards, in order, with who did it and why
* No e-mail or internal id on a public page, in an audit record or in a log
* Existing quizzes and runs change nothing; a run without rules shows nothing new
* Plugins import only `app.contracts`; storage and transactions stay in the domain ([ADR-0037](0037-providers-and-plugins.md))

## Considered Options

* Rules copied onto each run, with tiers, contact and source as settings; alternates drawn together with the winners; every draw action a new row
* Rules defined once on the quiz and read live by every run
* A draw that picks one new winner each time a winner does not claim, with no alternates

## Decision Outcome

Chosen option: "Rules copied onto each run, with tiers, contact and source as settings; alternates drawn together with the winners; every draw action a new row", because a run's rewards then stay as they were announced, the order of alternates is fixed by the same random draw that picked the winners, and the history can be replayed.

Rules:

* **Kinds.** `threshold` (unit `percent`, `points` or `correct`, a value), `participation`, `manual` and `draw` (a minimum in percent or points or none, winners ≥ 1, alternates 0–20, default 2). The direct entitlement of `FR-36` is both `participation` (everyone with a valid official attempt, at once) and `manual` (participants the admin picks). Each rule has a name, a description and claim instructions per quiz language; a missing text falls back to the quiz's default language field by field.
* **Where rules come from.** A rule belongs to a run, or to the quiz's template when it has no run. The setting `reward_source` (`none` default, `previous_run`, `quiz`; global and quiz) decides what a new run copies when it is planned or opened; `previous_run` falls back to the template when the quiz has no earlier normal run. A run then keeps its own copy; a template change does not reach planned runs. A run opened directly, without a plan, gets its rules only from the source.
* **Fixed once open.** Kind, unit, value, minimum, winners and alternates change only while the run is planned, or on the template. Names, descriptions and claim instructions change at any time, since they change only what is shown.
* **Tiers.** The setting `reward_thresholds` (`highest` default, `all`; global and quiz, copied into `QuizRun.rewards_json`, fixed once open) applies to threshold rules only. Under `highest` the participant gets the threshold with the largest share of the attempt's own maximum (points over maximum points, correct answers over the attempt's questions), so mixed units still compare; equal shares go to the first rule in order. Participation, manual and draw rules always add up.
* **Reached** means `>=` on exact decimals, against the attempt's own maximum including manual points ([ADR-0033](0033-image-answer-question-type.md)).
* **Entitlements** follow the participant's official attempt (`results.official_attempt`): granted in the submission transaction, recomputed when grading ends or a later attempt becomes official. An attempt waiting for grading counts for nothing. A recomputation cancels only a threshold entitlement it granted itself and that is not handed over yet, with the reason "no longer reached"; it never grants back a rule an admin cancelled for that participant. Participation is never taken back by a recomputation. Statuses are `granted`, `handed_over` and `cancelled`; sources `auto`, `manual` and `draw`. The admin hands over a granted entitlement, or cancels a granted or handed-over one with a reason.
* **Conflicts.** Rules are refused with the data profile `none`, with answers after each question ([ADR-0035](0035-immediate-solutions-only-without-competition.md)) and, under the setting `winner_contact = require_email`, when a run with a draw rule does not require an e-mail. `winner_contact` (`warn` default, `require_email`, `silent`; global and quiz, copied into `QuizRun.rewards_json`, fixed once open) otherwise only warns in the run plan. The system sends no e-mail.
* **The draw.** Only on the admin's command, on a closed or archived normal run that keeps scores and has nothing waiting for grading. The eligible set is rebuilt at every action from participants with an official attempt that meets the rule's minimum, ordered by participant id and fingerprinted with SHA-256. `secrets.SystemRandom().sample` draws `winners + alternates` at once (`"secrets.SystemRandom.sample+sha256"`): the first are winners, the rest alternates ranked 1..M. With fewer eligible than requested it draws everyone and says how many; with nobody it refuses and stores nothing. Winners get an entitlement of source `draw`; alternates get none.
* **Repeats, each with a required reason:**
  * *Move up*: the winner's place goes to the first alternate who still has a participant and is eligible now. Alternates passed over keep their place and may be promoted later if they become eligible again.
  * *Substitute*: one new winner drawn from the eligible set minus everyone the current draw has drawn, winners and alternates; refused when nobody is left.
  * *Redraw*: the whole draw again; the previous chain is superseded and its granted entitlements cancelled.
  * A replaced winner's granted entitlement is cancelled with the reason. A handed-over entitlement is never cancelled by a draw action, and a draw never gives a participant a second active entitlement of the same rule.
* **History only grows.** Every action is a new `Draw` row with its `DrawEntry` rows (winner, alternate, or the winner taken out); a move-up and a substitute point at the draw they amend, a redraw at the one it supersedes. No row is updated or deleted. Each row keeps time, admin id, run, rule, a SHA-256 of the rule's structure, eligible count and fingerprint, algorithm and reason. `audit_event` gets only the draw id, the rule id, the count, the fingerprint and the selected pseudonyms (the full record is the `Draw` row), and `draw.completed` is emitted ([ADR-0016](0016-in-process-events-no-broker.md)).
* **Pseudonym.** Each draw entry keeps a salted HMAC-SHA256 of the participant id with the server secret next to the participant link, so D3 can drop the link and keep the draw readable (`FR-39`).
* **Refresh is a direct call, not an event.** `rewards.refresh` runs inside the submit and grading transactions because `events.emit` dispatches on commit, and the grant must be stored in the same transaction as the attempt.
* **Plugins in use cannot be disabled.** `rewards.threshold` cannot be disabled while a planned, open or closed normal run has a threshold rule (or a draw rule with a minimum), and `drawings.manual` while one has a draw rule; both are usage checks like the one for question types, so a submission never meets a disabled plugin.
* **Publishing winners** is a per-rule switch, off by default and audited. The public scoreboard page then names the winners by nickname, else by the anonymous label of [ADR-0051](0051-scoreboard-participants-and-official-attempt.md), also when the board itself is hidden. E-mails are shown only on the admin's rewards and draw pages.
* **Test runs** never get rules, entitlements or draws ([ADR-0044](0044-preview-and-test-links.md)). A run with rules sets the participant cookie, like a visible scoreboard.
* **Split.** The plugin `rewards.threshold` (port `reward`) says which thresholds an attempt reaches and applies the tier setting; `drawings.manual` (port `drawing`) orders, fingerprints and selects. Rules, entitlements, draw records, transactions and pages live in `app/domain/rewards.py`, `app/domain/draws.py` and `app/api/admin_rewards.py`, the same split as `results.local` (ADR-0051).

* **A reward is renamed on the spot (addendum 2026-11-11).** The name in the quiz's default language has a pencil beside the summary of the reward's row (AC-160). It saves only the text through `rewards.save_texts`, so it works at any time, on a running run too, and the structure stays as it opened; the audit entry `reward.texts_saved` carries no name.

### Consequences

* Good, because a prize changes hands only by an admin's action or by a better or regraded attempt before it is handed over
* Good, because alternates come from the same audited random draw as the winners, so a move-up needs no new randomness
* Good, because the history replays the current winners from rows that never change
* Bad, because rules are copied, so a fix to the template must be repeated on runs already planned
* Bad, because the official attempt for rewards and draws is chosen over all the participant's attempts of the run, whatever the scoreboard's revision mode; under `separate` or `latest` the board may count another attempt
* Bad, because the draw is auditable only at application level, not towards the database admin (ADR-0013)

### Confirmation

AC-09, AC-10, AC-12, AC-16, AC-18, AC-90 to AC-93.

## More Information

Refines [ADR-0013](0013-manual-draw-csprng-append-only-audit.md). Deleting or pseudonymising draw data when retention ends comes with D3; export of entitlements and draws with D2. Design: `docs/superpowers/specs/2026-11-08-c5-rewards-and-draw-design.md`.
