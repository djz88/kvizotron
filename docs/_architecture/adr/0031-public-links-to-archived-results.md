---
status: accepted
date: 2026-11-05
---

# ADR-0031: Public links to archived run results

## Context and Problem Statement

FR-02 gives archived runs view-only access "subject to permissions and retention", and the spec left
open whether results can be public. Scoreboards contain nicknames, while events often want to show
their results afterwards.

## Decision Drivers

* Privacy by default
* Events can share their results
* Same data exposure rules as the live scoreboard

## Considered Options

* Off by default, per-run switch
* Inherited from scoreboard visibility
* Never public

## Decision Outcome

Chosen option: "Off by default, per-run switch", because privacy stays the default while the admin can
still publish results.

Rules:

* Only columns allowed for the public scoreboard are shown (FR-29).
* The public view ends when retention expires.

### Consequences

* Good, because archived results are not public without a decision
* Bad, because it adds one setting
* Bad, because an admin may forget to enable it

### Confirmation

Integration test of the archived-run view: switch off, switch on, retention expired.

## More Information

Resolves [OQ-10](../open-questions.md).
