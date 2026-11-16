---
status: accepted
date: 2026-11-07
---

# ADR-0049: Participants identified per run only when needed, an access code per run

## Context and Problem Statement

`FR-27`, `FR-28`, `FR-32` and `FR-06` ask for repetition rules, an anonymous cookie identity, duplicate nickname rules, name and e-mail collection and an optional access code per run. [ADR-0011](0011-anonymous-cookie-participant-identity.md) chose a cookie without a uniqueness guarantee and [ADR-0030](0030-rate-limit-thresholds.md) a limit of failed codes. Open was where the rules live, when a cookie exists, how a code is remembered, and what an unfinished attempt means when repeating is forbidden.

## Decision Drivers

* Security proportional to a quiz: the simplest mechanism that stops reloading, a new tab or an abandoned attempt from giving a second try
* No cookie and no personal data when a run's rules do not need them
* An access code never readable after it was set
* The server alone decides what is accepted, also under two tabs at once

## Considered Options

* Rules as settings copied onto the run, a cookie only on need, the code per run
* A cookie on every run, rules read live from the quiz
* The code as an inherited setting

## Decision Outcome

Chosen option: "Rules as settings copied onto the run, a cookie only on need, the code per run", because it keeps one run's rules fixed for everyone in it and stores nothing for runs that do not ask for it.

Rules:

* Six settings (`repeat_attempts`, `unfinished_attempt`, `ask_name`, `ask_email`, `ask_when`, `duplicate_names`) are declared by the plugin `participants.basic` and inherited global → quiz. They are copied onto the run when it is planned or opened, editable on the plan form, and fixed once it opens. They have no question level, as they concern the whole attempt ([ADR-0042](0042-settings-inherited-and-declared.md)). A test run reads them live with repeating allowed.
* The plugin holds the pure decisions behind the contract `ParticipantPolicyPlugin`: name cleaning and comparison, e-mail format, and what a returning participant gets. The domain holds the `Participant` rows, the checks and the transactions.
* A participant row and the cookie `kvz_p_<run>` exist only when repeating is forbidden or a name or e-mail is asked. The cookie holds a random key; the database keeps an HMAC of the key with the run id, so one browser gives unrelated hashes in different runs.
* With repeating forbidden, an unfinished attempt either continues (same questions, the limit keeps running, an expired one ends the participant's play), is used up by starting, or counts only when submitted. In the last mode a new start marks the previous attempt `ABANDONED`, and every token entry refuses it. That mode gives a fresh limit after an abandoned attempt, which is its meaning; an admin wanting a hard limit picks one of the other two.
* The repetition check and the duplicate-name check run in the same transaction as the write, at start and at submission. Only submitted attempts hold a name. An automatic submission never fails on a name: a missing or taken one is dropped, marked, and offered for filling in through the private result link until the run is archived. The client's automatic flag needs no trust, as it gains no points and only relaxes the name rules.
* Name and e-mail are asked before the start or at the end, a setting with the end as default (`FR-32`).
* The access code belongs to the run, is not inherited, and is stored only as a password hash. The admin sees a new code once, in the response that set it. A correct code is remembered in a separate signed cookie `kvz_c_<run>` whose version is an HMAC of the stored hash, so a changed code locks out those who have not started. A locked start is refused before any name check or participant row, except a resume of an attempt already running.
* Failed codes are limited per client IP in process memory, 10 per minute by default (`KVZ_CODE_ATTEMPTS_PER_MINUTE`). The IP is the first `X-Forwarded-For` value, which Caddy overwrites from the real client, else `REMOTE_ADDR`. (Amended by [ADR-0066](0066-single-container-image.md): the address is the N-th `X-Forwarded-For` value from the right, N = `KVZ_TRUSTED_PROXIES`, the one the outermost trusted proxy appended; with Caddy that is the same single value.)
* Pages that echo a typed name or e-mail are `private, no-store`. A refused fill-in under `/v/<token>` answers 200, so the token never reaches a request log.

* **An admin renames a nickname (addendum 2026-11-11).** In the table of attempts of a run an admin can change a participant's nickname, for a name that should not be on a scoreboard (AC-161). The rules hold as for the participant: no empty name, at most 40 characters, and no name another participant with a finished attempt holds where equal names are forbidden. The cached scoreboard is cleared and the audit entry `participant.renamed` carries neither name.

### Consequences

* Good, because a run without these rules behaves exactly as before and stores nothing new
* Good, because two tabs, a reload or an abandoned attempt cannot give a second counted attempt under "forbid"
* Bad, because the cookie still does not guarantee one person: another browser or a private window is a new participant (ADR-0011)
* Bad, because the failed-code limit resets on restart and is per worker process
* Bad, because names and e-mails are kept until retention arrives in D3

### Confirmation

AC-70 to AC-76.

## More Information

Refines [ADR-0011](0011-anonymous-cookie-participant-identity.md) and applies [ADR-0030](0030-rate-limit-thresholds.md).

Refined by [ADR-0056](0056-retention-job-summary-held-runs.md): since D3 names and e-mails are deleted with the run's data or on an erasure request.
