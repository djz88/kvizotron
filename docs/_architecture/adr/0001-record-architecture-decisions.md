---
status: accepted
date: 2026-11-04
---

# ADR-0001: Record architecture decisions as MADR in docs/_architecture/adr

## Context and Problem Statement

Kvízotron's v1.0 decisions were made in a brainstorming spec. We need a durable, reviewable record that survives the removal of that spec.

## Decision Drivers

* Traceability of decisions to requirements
* Low tooling overhead
* English documentation

## Considered Options

* MADR 4 Markdown files
* Nygard-style ADRs
* Wiki pages

## Decision Outcome

Chosen option: "MADR 4 Markdown files", because it captures options and consequences explicitly and lives next to the code.

### Consequences

* Good, because decisions versioned with code, reviewable in PRs
* Bad, because requires discipline to add ADRs for new decisions

### Confirmation

Every new architecturally significant change adds or supersedes an ADR; template [0000-template.md](0000-template.md).

## More Information

Statuses: `proposed`, `accepted`, `rejected`, `deprecated`, `superseded by ADR-NNNN`. Open items are tracked in [../open-questions.md](../open-questions.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
