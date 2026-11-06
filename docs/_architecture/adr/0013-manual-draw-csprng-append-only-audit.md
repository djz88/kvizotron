---
status: accepted
date: 2026-11-04
---

# ADR-0013: Manual prize draw with CSPRNG and append-only audit

## Context and Problem Statement

Prize draws must be trustworthy and reviewable without overpromising cryptographic proof.

## Decision Drivers

* Explicit admin control
* Auditability
* PII minimisation

## Considered Options

* Admin-triggered draw over deterministic eligible snapshot, CSPRNG, append-only audit
* Automatic draw at deadline
* Verifiable public randomness (commit-reveal)

## Decision Outcome

Chosen option: "Admin-triggered draw over deterministic eligible snapshot, CSPRNG, append-only audit", because it is auditable at application level with low complexity.

### Consequences

* Good, because repeat draws recorded with reason, originals never overwritten
* Bad, because not cryptographically indisputable towards the DB administrator

### Confirmation

[AC-12](../acceptance-criteria.md).

## More Information

FR-37 – FR-39; [../plugins/drawing.md](../plugins/drawing.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
