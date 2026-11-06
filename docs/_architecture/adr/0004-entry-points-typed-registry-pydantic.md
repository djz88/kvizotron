---
status: accepted
date: 2026-11-05
---

# ADR-0004: Python entry points for discovery, typed registry ports, Pydantic contracts

## Context and Problem Statement

Plugins must be discovered and registered, but business logic must stay explicit and testable. The
original spec proposed pluggy, yet services call modules through a typed registry, so pluggy would be
used only to find plugins.

## Decision Drivers

* Explicit call sites
* Validated configuration
* Fewest dependencies and mechanisms

## Considered Options

* Python entry points (`importlib.metadata`) + own typed registries + Pydantic
* pluggy discovery + own typed registries + Pydantic
* pluggy hooks for all logic

## Decision Outcome

Chosen option: "Python entry points (`importlib.metadata`) + own typed registries + Pydantic", because
the standard library covers discovery and the registry already covers calls.

### Consequences

* Good, because there is one dependency and one mechanism fewer
* Good, because services call `registry.get('choice.single')`-style typed ports
* Good, because config is validated by schema and snapshotted when it affects scoring
* Bad, because it deviates from the original spec
* Bad, because several modules joining one operation would need extra code; shared reactions use events ([ADR-0016](0016-in-process-events-no-broker.md))

### Confirmation

Code review: modules are reached through the registry. A sample plugin is discovered without kernel changes ([AC-01](../acceptance-criteria.md)).

## More Information

[../modules/kernel.md](../modules/kernel.md), [../../plugin-api.md](../../plugin-api.md). pluggy can be
added later behind the registry if ordered hooks become necessary, without changing modules. Modules
are Django apps; entry points feed `INSTALLED_APPS` at startup ([ADR-0036](0036-django-web-framework-and-orm.md)).
