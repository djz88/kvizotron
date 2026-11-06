---
status: accepted
date: 2026-11-05
---

# ADR-0023: Entity identifier format

## Context and Problem Statement

The spec does not define an ID format, yet IDs appear in public URLs (`run_id`) and in the signed
attempt token. IDs must not be enumerable and must index well in SQLite.

## Decision Drivers

* Non-enumerable public IDs
* Time-sortable values for index locality
* No extra dependency
* IDs can be generated outside the database (stateless mode)

## Considered Options

* UUIDv7 everywhere
* ULID
* Integer primary key plus a separate random public ID

## Decision Outcome

Chosen option: "UUIDv7 everywhere", because it is a standard (RFC 9562), available in the Python
standard library (`uuid.uuid7()`), time-sortable and uses a single ID type for all entities.

Rules:

* An ID is **not a secret**. Access is protected by the signed token and authorisation checks, never
  by the ID being hard to guess.
* Secret values (session tokens, anonymous cookie keys, access codes) come from a CSPRNG and are never
  UUIDv7 values.
* Physical storage: Django `UUIDField`, on SQLite `char(32)` ([ADR-0036](0036-django-web-framework-and-orm.md),
  [../providers/persistence-sqlite.md](../providers/persistence-sqlite.md)).

### Consequences

* Good, because there is one ID type and no extra dependency
* Good, because IDs cannot be walked sequentially
* Bad, because an ID reveals its creation time (harmless for runs; participant IDs are not public)
* Bad, because IDs are larger than integers and make URLs longer

### Confirmation

Data-model review in Stage A; a test verifies that secrets are not generated as UUIDv7.

## More Information

Resolves [OQ-02](../open-questions.md).
