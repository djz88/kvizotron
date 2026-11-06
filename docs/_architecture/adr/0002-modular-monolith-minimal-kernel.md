---
status: accepted
date: 2026-11-04
---

# ADR-0002: Modular monolith with a minimal kernel

## Context and Problem Statement

The product requires full modularity of capabilities (including auth and persistence) while staying simple to operate for ~50 concurrent users on one server.

## Decision Drivers

* Simple operations
* Replaceable capabilities without kernel change
* No distributed-systems overhead

## Considered Options

* Modular monolith with minimal kernel and provider contracts
* Classic layered monolith
* Microservices
* Dynamic plugin install from UI with process isolation

## Decision Outcome

Chosen option: "Modular monolith with minimal kernel and provider contracts", because it delivers replaceable capabilities with single-process operations.

### Consequences

* Good, because every capability (incl. auth, persistence) is a provider of a registered contract
* Good, because single deployable unit
* Bad, because contract design effort up front
* Bad, because plugins run in-process and are trusted (installed by operator only)

### Confirmation

[AC-01](../acceptance-criteria.md), [AC-02](../acceptance-criteria.md); contract tests in `tests/contracts/`.

## More Information

Kernel scope: bootstrap, process config, contract registry/verification, dependency resolver, event dispatch, lifecycle. See [../modules/kernel.md](../modules/kernel.md). Not required: untrusted code install from UI, plugin process isolation, microservices. Terminology refined by [ADR-0037](0037-providers-and-plugins.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
