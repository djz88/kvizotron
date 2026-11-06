# Provider: persistence-sqlite

| | |
|---|---|
| Contract | `PersistenceProvider` |
| Package | `app/providers/persistence_sqlite/` |
| Stage | A |
| Decision | [ADR-0036](../adr/0036-django-web-framework-and-orm.md) |

## Behaviour

- Supplies Django's `DATABASES` settings: SQLite in **WAL** mode on a local persistent volume, with
  `transaction_mode: IMMEDIATE` and a busy timeout. Application code uses the Django ORM and migrations.
- WAL allows concurrent reads with a write, but **only one writer**. Load testing is mandatory
  ([AC-15](../acceptance-criteria.md)).
- The SQLite file in WAL mode **MUST NOT** be shared over a network filesystem.
- Submission logic is kept in a **short DB transaction**; `database is locked` is handled with
  retry/backoff.
- Atomic transactions use `transaction.atomic`; each module owns its migrations.
- Replacing the provider requires a dedicated data migration; switching happens on restart, never
  uncontrolled at runtime ([AC-02](../acceptance-criteria.md)).
- `healthcheck()` backs the container healthcheck.

## Contract tests

Persistence contract tests run against this provider only; a second persistence provider is LATER
([ADR-0027](../adr/0027-demo-alternative-persistence-provider.md)). Domain and module code must not use
SQLite-specific SQL or behaviour.

## Storage notes

- UUIDv7 IDs use Django `UUIDField`, stored as `char(32)` on SQLite: [ADR-0023](../adr/0023-id-format.md).
