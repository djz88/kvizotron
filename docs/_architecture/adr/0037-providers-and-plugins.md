---
status: accepted
date: 2026-11-05
---

# ADR-0037: Providers and plugins are separate module kinds

## Context and Problem Statement

[ADR-0002](0002-modular-monolith-minimal-kernel.md) called every capability a provider, and the
documentation used "provider" and "plugin" as synonyms. Infrastructure such as the database and product
features such as question types behave differently: how many can be active, who selects them and when
they may change.

## Decision Drivers

* Terms that say how a module behaves
* Clear rules for selection and activation

## Considered Options

* Two module kinds: provider and plugin
* One kind, every module is a plugin

## Decision Outcome

Chosen option: "Two module kinds: provider and plugin".

* **Module** is the common term: one installed unit declaring a manifest.
* **Provider** supplies infrastructure: authentication, persistence, media storage, retention,
  import/export. The operator selects it; changing it means a controlled restart and, if needed, a data
  migration. Authentication, persistence, media storage and retention have exactly one active provider;
  import/export may have several, one per format.
* **Plugin** supplies a product feature: question types, scoring, quiz flow, participant policy, result
  views and dashboards, rewards, draws, themes. Several can be active. Admins enable them without a
  restart and may select them per quiz where the manifest allows it.

`ResultProvider` is split: storing attempts and results belongs to the domain, while scoreboards,
statistics and dashboards are `ResultViewPlugin` modules.

The contract tables are in [../modules/contracts.md](../modules/contracts.md).

### Consequences

* Good, because selection and restart rules follow from the module kind
* Good, because new result views and dashboards do not touch result storage
* Bad, because most contracts and documentation are renamed before any code exists
* Bad, because the kernel has to handle two activation paths

### Confirmation

Each manifest declares `kind`; the kernel rejects a second active provider where exactly one is allowed
([AC-02](../acceptance-criteria.md)). Contract tests in `tests/contracts/` cover both kinds.

## More Information

Refines the terminology of [ADR-0002](0002-modular-monolith-minimal-kernel.md). The classification of
media storage, retention, scoring, participant policy, rewards and draws was proposed during
implementation planning; the user named database, auth and import/export as providers, and themes,
question types and result or dashboard views as plugins.
