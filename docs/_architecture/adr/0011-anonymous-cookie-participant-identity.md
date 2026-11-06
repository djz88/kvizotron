---
status: accepted
date: 2026-11-04
---

# ADR-0011: Anonymous cookie as participant identity, without uniqueness guarantee

## Context and Problem Statement

Participation is without registration; repeat attempts must still be distinguishable.

## Decision Drivers

* No registration
* Privacy
* Honest guarantees

## Considered Options

* Anonymous cookie key (stored hashed) per run
* Mandatory e-mail verification
* Device fingerprinting

## Decision Outcome

Chosen option: "Anonymous cookie key (stored hashed) per run", because it is privacy-friendly and enough for casual competitions.

### Consequences

* Good, because no accounts for participants
* Bad, because cannot guarantee one participation per person; multiple devices/cleared cookies bypass limits

### Confirmation

Documented as non-guarantee in [../overview.md](../overview.md).

## More Information

FR-27, FR-28; [../plugins/participants.md](../plugins/participants.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
