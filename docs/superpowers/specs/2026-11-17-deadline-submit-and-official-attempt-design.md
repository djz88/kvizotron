# Submissions at the deadline and the counted attempt for rewards — design

Status: decided with the owner in chat on 2026-11-17 (TD-091, TD-047). Not implemented.

## Why

Two open debt items before v1.0 can cost a participant their result or their prize:

- **TD-091.** The `submit` bucket (`KVZ_SUBMITS_PER_MINUTE`, default 120 per minute per client
  address, ADR-0058) counts every submit request. The page repeats an automatic submission at the
  deadline up to six times after a lost connection or a 5xx, with the same submission key
  (ADR-0060), and once after a 429. A class behind one school address that finishes together
  spends the bucket on repeats; a refused send waits `Retry-After` (60 s), which is after the
  deadline, and the server then rejects it (`attempt_expired`, no grace, ADR-0025). The attempt is
  lost.
- **TD-047.** The scoreboard picks each participant's counted attempt according to the run's
  revision mode (ADR-0065: `percent` default — all revisions in one table, each attempt measured
  against its own revision's maximum; `latest` — only the run's current revision; `separate` — one
  table per revision). Rewards, the draw and the pass mark use `results.kept()`, which picks over
  all attempts by points. After a switch to a revision with a different maximum, the prize can go
  to a different attempt (or participant) than the scoreboard shows. ADR-0053 lists this as a
  known drawback.

## Decisions (the owner's)

1. **One attempt, one place in the `submit` bucket.** Within the bucket's window, sends of the same
   attempt from the same address count once. Repeats of an attempt already counted pass the
   limiter. Everything else about the bucket stays: the limit, the address key, the 429 with
   `Retry-After`, a refused send for an attempt not yet counted.
2. **The counted attempt for rewards follows the scoreboard.** One rule for "which attempt
   counts" everywhere a run decides by it (rewards, draw eligibility, participation, the pass mark
   on the result, the attempts table's kept figures, export):
   - `percent` (default): the run's rule (`best`, `first`, `last`, `average`) over all revisions,
     each attempt as a percent of its own revision's maximum — exactly as the board picks it.
   - `latest`: only attempts of the run's current revision count, picked by the run's rule.
   - `separate`: like `percent` (one counted attempt per participant, by percent over all
     revisions), because a participant can win only once while the board shows one table per
     revision.
   Within one revision percent and points order the same, so runs that never switched revision
   behave exactly as today.

## Consequences of decision 2 (the owner's choice, spelled out)

- Under `latest`, a participant whose only attempts are on an older revision has no counted attempt:
  they are off the board, their automatic threshold entitlement that is not handed over is
  cancelled as "no longer reached" by the usual recomputation, and they are not eligible for a
  draw. Participation, handed-over and admin-given entitlements stay (ADR-0053).

## Decided by the agent (owner may change)

- **`average` figures.** The counted attempt under `average` is picked as today's board does (mean
  of percents), and the figures that thresholds, the pass mark and the result page read stay
  today's: the mean of points over the mean of maxima (`_average_figures`) — the points the board
  shows beside an `average` row. Only runs with `average` and several revisions of different
  maxima can see the two differ.
- **A changed revision mode re-runs rewards.** Saving the scoreboard settings with another revision
  mode, and switching the run to another revision, recompute entitlements exactly as a newly
  official attempt does today (ADR-0053: only the run's own not-handed-over automatic thresholds
  are cancelled, nothing an admin cancelled is granted back, participation is never taken back).
  Draws already held stay in their unchangeable history; the next draw action rebuilds its
  eligible set with the new rule (it already rebuilds at every action).
- **The limiter's memory of counted attempts** lasts the bucket's window (60 s) from the latest send
  of that attempt, and is swept with the other idle keys. A repeat later than that counts again;
  by then the deadline has passed and the server rejects the send anyway (ADR-0025).

## Goals

- TD-091 and TD-047 resolved, each with tests that fail before the change.
- ADR-0058 gets an addendum for decision 1; ADR-0053 gets an addendum for decision 2 (its
  "Bad, because …" line about revision modes is answered); TD-091 and TD-047 move to the archive
  with a resolution line.
- `make load` still passes its 50-from-one-address scenario.

## Non-goals

- No change to ADR-0025 (no grace after the deadline) or to the repeat schedule in
  `countdown.js`.
- No change to the `start`, `login` or `code` buckets.
- No change to how the scoreboard ranks.
- No new setting.

## Anti-goals

- A client that sends many *different* attempt ids must still be limited as today.
- Memory of the limiter must stay bounded (the existing sweep drops idle keys; the new record of
  counted attempts must be swept the same way).
- A change in which attempt counts must re-run what depends on it the same way a later attempt
  becoming official does today (entitlement recomputation per ADR-0053), without granting back
  what an admin cancelled.

## Constraints

- Request limits stay in the memory of the single app process (ADR-0058, ADR-0066).
- The limiter key stays the client address from `rate_limit.client_ip` (`KVZ_TRUSTED_PROXIES`).
- `results` stays the single owner of "which attempt counts"; `rewards` keeps calling
  `results.official_attempt` / `results.kept`.

## Left to the builder

- The limiter's data structure for "attempts counted in this window" and its sweep.
- Where the attempt id is read for the limiter (the URL's `attempt_id` is enough; the limiter
  runs before the attempt is loaded today and may keep doing so).
- How `kept()` reuses the board's per-percent pick (`_pick_by_percent`, `_maxima`,
  `_shown_candidates`) without duplicating it.
