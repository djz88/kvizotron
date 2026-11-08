---
status: accepted
date: 2026-11-04
---

# ADR-0020: Browser-local resume of unsubmitted attempts, treated as untrusted

## Context and Problem Statement

Participants may lose connection or close the tab during a quiz.

## Decision Drivers

* Resilience
* No server-side drafts of PII
* Integrity

## Considered Options

* localStorage with short TTL, opt-in per quiz, server re-validates
* Server-side draft storage
* No resume

## Decision Outcome

Chosen option: "localStorage with short TTL, opt-in per quiz, server re-validates", because it adds resilience without trusting the client.

### Consequences

* Good, because works offline briefly
* Bad, because an image answer must be selected again after resuming
* Bad, because only same browser; public computers may retain data until TTL

### Confirmation

[AC-11](../acceptance-criteria.md).

## More Information

Refined by [ADR-0050](0050-data-profile-and-local-resume.md): local resume is on by default, and a copy is resumed through its token. FR-22; [../plugins/quiz-flow.md](../plugins/quiz-flow.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
