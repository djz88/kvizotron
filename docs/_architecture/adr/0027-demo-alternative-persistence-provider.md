---
status: accepted
date: 2026-11-05
---

# ADR-0027: Demonstration alternative provider

## Context and Problem Statement

The spec's AC-02 asked for a demonstration alternative auth/persistence provider that passes the same
contract tests, as proof that these capabilities are replaceable. For a quiz application on SQLite, a
second database implementation costs more than the proof is worth today.

## Decision Drivers

* Proportionate effort
* Evidence that the provider boundary works
* No additional services in CI

## Considered Options

* Test-only authentication provider; second persistence provider deferred
* PostgreSQL test-only provider through a shared SQLAlchemy layer
* In-memory test-only persistence provider

## Decision Outcome

Chosen option: "Test-only authentication provider; second persistence provider deferred", because
SQLite is sufficient for v1.0 and a second database implementation has no current user.

Rules:

* A small test-only authentication provider with a fixed account passes the shared contract tests. It
  is never shipped to production.
* `PersistenceProvider` remains a contract ([ADR-0036](0036-django-web-framework-and-orm.md)),
  and its contract tests run against the SQLite provider only.
* Domain and module code must not use SQLite-specific SQL or behaviour; this is checked in code review.
* A second persistence provider is LATER, delivered when a real need appears.

### Consequences

* Good, because it costs almost no work and adds no CI service
* Bad, because replacing the database stays an unproven claim in v1.0
* Bad, because code can become bound to SQLite unnoticed, making a later replacement more expensive
* Bad, because it narrows the spec's AC-02; the criterion was rewritten accordingly

### Confirmation

[AC-02](../acceptance-criteria.md).

## More Information

Resolves [OQ-06](../open-questions.md).
