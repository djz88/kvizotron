---
status: accepted
date: 2026-11-05
---

# ADR-0016: Synchronous in-process events, no message broker

## Context and Problem Statement

Modules react to domain events, and infrastructure must stay minimal. The original spec allowed
synchronous dispatch or a simple database queue without choosing between them.

## Decision Drivers

* Simplicity
* Atomic submission independent of event delivery

## Considered Options

* Synchronous in-process dispatch only
* Simple database queue
* RabbitMQ or Kafka
* Redis pub/sub

## Decision Outcome

Chosen option: "Synchronous in-process dispatch only", because nothing long-running depends on events:
retention and cleanup are run by the management CLI.

### Consequences

* Good, because there is no broker or queue to operate
* Bad, because a handler runs inside the request and must stay short; long work belongs in CLI jobs

### Confirmation

Review of event handlers.

## More Information

Events: `quiz.published`, `run.opened`, `attempt.submitted`, `run.closed`, `draw.completed`, `retention.executed`.
A database queue can be added later if a real need appears.
