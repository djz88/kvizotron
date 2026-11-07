---
status: accepted
date: 2026-11-05
---

# ADR-0034: Modules declare requirements on quiz and run settings

## Context and Problem Statement

Most behaviour is configurable by the admin, but some modules only work with certain settings. The
image answer type cannot work with an immediately visible public scoreboard or without stored answers.
Hardcoding such exceptions in the kernel or the scoreboard would break modularity.

## Decision Drivers

* Modules stay self-contained
* The admin keeps control and sees why a setting is required
* Invalid combinations never reach a published quiz

## Considered Options

* Declarative requirements in the plugin manifest, validated by the kernel
* Hardcoded exceptions per module
* Warnings only, no enforcement

## Decision Outcome

Chosen option: "Declarative requirements in the plugin manifest, validated by the kernel", because it
works for future modules without kernel changes.

Rules:

* A module declares in its manifest which settings it requires to be enabled, set to allowed values or
  disabled (`settings_requirements`).
* When a module is selected, the admin UI shows the requirements and offers to apply them.
* The kernel validates the requirements when a quiz is published and a run is opened. A conflict blocks
  the action with an explanation.
* Requirements are declarative values only, with no code executed.
* Requirements of different modules that contradict each other block the combination.

### Consequences

* Good, because the same mechanism covers all module dependencies on settings, in the spirit of FR-17 and FR-31
* Good, because no module-specific exception exists in the core
* Bad, because settings need stable names that become part of the plugin contract

### Confirmation

[AC-17](../acceptance-criteria.md).

## More Information

Defined by FR-46 in [../modules/kernel.md](../modules/kernel.md). Extends
[ADR-0021](0021-plugin-manifest-and-versioning.md). First user: [ADR-0033](0033-image-answer-question-type.md), through `reveal_moment` ([ADR-0047](0047-image-answer-photo-visibility.md)). A requirement states the values it refuses, the value `Use` applies, and a reason.
