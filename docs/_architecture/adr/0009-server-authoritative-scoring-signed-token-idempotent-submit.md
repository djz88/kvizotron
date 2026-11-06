---
status: accepted
date: 2026-11-04
---

# ADR-0009: Server-authoritative scoring with signed attempt token and idempotent submission

## Context and Problem Statement

Public anonymous clients can tamper with payloads and retry submissions.

## Decision Drivers

* Result integrity
* Idempotence under retries
* No secret answers on the client

## Considered Options

* Signed attempt_token + server re-scoring + unique submission_key
* Trust client score
* Server-side session per attempt only

## Decision Outcome

Chosen option: "Signed attempt_token + server re-scoring + unique submission_key", because the server never trusts client score, solution or times.

### Consequences

* Good, because token carries run_id, revision_id, attempt_id, start, expiry, manifest hash — no solutions
* Good, because atomic idempotent result write
* Bad, because token key management needed

### Confirmation

[AC-08](../acceptance-criteria.md), [AC-15](../acceptance-criteria.md).

## More Information

Flow: [../architecture.md](../architecture.md#4-runtime-flow-start-and-submit-an-attempt). Signing mechanism: [ADR-0024](0024-attempt-token-signing.md). Manual points from an admin: [ADR-0033](0033-image-answer-question-type.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
