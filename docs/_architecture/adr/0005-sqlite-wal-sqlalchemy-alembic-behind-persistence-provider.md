---
status: superseded by ADR-0036
date: 2026-11-04
---

# ADR-0005: SQLite (WAL) via SQLAlchemy 2.x and Alembic behind PersistenceProvider

## Context and Problem Statement

Small self-hosted deployment needs reliable storage with minimal operations; persistence must remain replaceable.

## Decision Drivers

* No external DB service
* Transactions and migrations
* Replaceability

## Considered Options

* SQLite WAL + SQLAlchemy 2.x + Alembic behind PersistenceProvider
* PostgreSQL from day one
* Document store

## Decision Outcome

Chosen option: "SQLite WAL + SQLAlchemy 2.x + Alembic behind PersistenceProvider", because it is sufficient for ~50 concurrent participants and needs no extra service.

### Consequences

* Good, because zero-ops database on a local volume
* Good, because provider boundary allows a different DB later
* Bad, because single writer — submissions must be short transactions with `database is locked` retry/backoff
* Bad, because the application runs as a single process; in-process rate limits ([ADR-0030](0030-rate-limit-thresholds.md)) also depend on it
* Bad, because must not live on a network filesystem
* Bad, because mandatory load test

### Confirmation

[AC-15](../acceptance-criteria.md) load test; [AC-02](../acceptance-criteria.md) contract tests.

## More Information

[../providers/persistence-sqlite.md](../providers/persistence-sqlite.md). Second provider deferred: [ADR-0027](0027-demo-alternative-persistence-provider.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
