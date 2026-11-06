---
status: accepted
date: 2026-11-05
---

# ADR-0025: Deadline boundary-second semantics

## Context and Problem Statement

FR-11 requires an unambiguously specified behaviour at the boundary second. Example: the deadline is
10:00:00 and the answers arrive at 10:00:00.4. Every such case needs one clear result, and last-moment
submissions should not be lost because of network delay.

## Decision Drivers

* Unambiguous and testable behaviour
* Matches the time a person sees
* Few submissions lost at the last moment

## Considered Options

* Whole boundary second accepted, with early automatic submission in the browser
* Millisecond-exact comparison
* Network grace period (for example 10 s)

## Decision Outcome

Chosen option: "Whole boundary second accepted, with early automatic submission in the browser",
because it matches the displayed time and stays strict in whole seconds.

Rules:

* The time that counts is the server time when the submission is received.
* Both `server_now` and the limit are truncated to whole seconds, then compared with `<=`.
  With a limit of 10:00:00, 10:00:00.9 is accepted and 10:00:01.0 is rejected.
* The limit is `min(deadline_at, started_at + attempt_limit)`, as in FR-11.
* The browser countdown submits automatically about 5 s before the limit.

### Consequences

* Good, because the rule is simple to explain and test
* Good, because few submissions are lost
* Bad, because the real limit can be up to 1 s longer than the configured one
* Bad, because the participant loses a few seconds of visible time
* Bad, because it needs a synchronised server clock (NTP) and reliable automatic submission in JS
* Bad, because a submission arriving late, including a slow image upload, is rejected; finishing in time is the participant's responsibility

### Confirmation

Boundary tests in [AC-07](../acceptance-criteria.md).

## More Information

Resolves [OQ-04](../open-questions.md). Refines [ADR-0010](0010-strict-server-side-deadline.md).
