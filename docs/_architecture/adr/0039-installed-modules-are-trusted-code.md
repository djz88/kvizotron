---
status: accepted
date: 2026-11-06
---

# ADR-0039: Installed modules are trusted code

## Context and Problem Statement

Scanners report dynamic imports in module discovery and `Markup()` around plugin output. Both follow from the
modular design ([ADR-0002](0002-modular-monolith-minimal-kernel.md), [ADR-0004](0004-entry-points-typed-registry-pydantic.md)),
so the project needs a stated position on what a module may do.

## Decision Drivers

* Adding a module needs no change to the core (AC-01)
* A plugin's mistake in escaping should be caught before release
* Security proportional to a quiz platform

## Considered Options

* Installed modules are trusted code; contract tests catch mistakes
* A list of allowed modules in the core
* Plugins return data, and the core renders it

## Decision Outcome

Chosen option: "Installed modules are trusted code; contract tests catch mistakes", because whoever can install a
package on the server can already run any code there, so a list adds no protection and breaks AC-01.

Rules:

* Dynamic import paths come only from manifests of installed packages, never from a request or from the database.
* Plugin output is marked safe. Each question type must render through an autoescaping template, and the shared
  contract suite tests this for both `render_public` and `render_admin`.

### Consequences

* Good, because new modules need no change to the core
* Bad, because the contract tests cover only the text they feed in, so a careless plugin could still have a hole elsewhere
* Bad, because a malicious package can do anything; choosing packages is the operator's responsibility

### Confirmation

`tests/contracts/question_type.py`, and startup refusal tests in `tests/kernel/`.
