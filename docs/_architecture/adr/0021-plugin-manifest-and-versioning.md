---
status: accepted
date: 2026-11-04
---

# ADR-0021: Plugin manifest with separate contract and config-schema versions

## Context and Problem Statement

Plugins evolve; old revisions must remain re-evaluable.

## Decision Drivers

* Compatibility checks at startup and publish
* Audit of old revisions

## Considered Options

* Manifest with id, version, api_compatibility, config_schema_version, requires/optional, activation_scope, migrations, assets
* Implicit versioning by package version only

## Decision Outcome

Chosen option: "Manifest with id, version, api_compatibility, config_schema_version, requires/optional, activation_scope, migrations, assets", because it makes compatibility explicit.

### Consequences

* Good, because incompatible plugins block publish/activation with explanation
* Good, because revisions store type id + version
* Bad, because replacing a plugin requires a migration strategy

### Confirmation

Startup check; [AC-01](../acceptance-criteria.md).

## More Information

[../../plugin-api.md](../../plugin-api.md). Extended by [ADR-0034](0034-module-requirements-on-settings.md).
Migrations belong to the module's Django app ([ADR-0036](0036-django-web-framework-and-orm.md)), so the
manifest has no `migrations` field.

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
