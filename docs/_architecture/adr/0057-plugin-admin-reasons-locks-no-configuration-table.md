---
status: accepted
date: 2026-11-09
---

# ADR-0057: Modules page with shared refusal reasons, always-on plugins, and no configuration table yet

## Context and Problem Statement

The kernel could enable and disable a plugin only from `manage.py`. An organiser needs a page, plain reasons for a refusal and a view of where a setting departs from its global value. Some plugins are requested by a fixed name, so disabling one breaks the application, and the kernel must not know what a quiz is. The data model also names a `plugin_configuration` table that no module needs.

## Decision Drivers

* The same rule must hold on the page and on the command line
* `app/kernel` must not import the domain
* A refusal is read by an admin in cs, en or uk
* Each setting keeps one place where it is changed (ADR-0042)
* No table without a user

## Considered Options

* Reasons: raising exceptions only; a non-raising list used by both callers
* Locks: a list of module ids in the kernel; a manifest field; a usage check per module
* Configuration: add `plugin_configuration` now; show the existing settings with links

## Decision Outcome

Chosen: `lifecycle.blockers(module_id, enabled)` returns `Blocker` objects (kind, text in the active language, an opaque target) and `set_enabled` raises from the same list, in English. A manifest field `always_on` locks a plugin. `name`, `description` and `always_on` are optional, so the plugin API stays within `>=1.0,<2.0`. Module pages show settings with links to where they are changed, and the differences from the global value. `plugin_configuration` is not created until a module needs it.

### Consequences

* Good: a rule cannot exist on the page and not in `manage.py`.
* Good: a planned run now blocks disabling, so it cannot open later with a disabled type.
* Bad: the check and the write are not one transaction; a run opened at that moment can slip through. Its attempts still work, because playing reads ports with `include_disabled=True`.
* Bad: `activation_scope` in manifests stays unused, because disabling applies to the whole installation.
