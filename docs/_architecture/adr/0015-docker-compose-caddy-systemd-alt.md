---
status: accepted
date: 2026-11-04
---

# ADR-0015: Docker Compose with Caddy; systemd as alternative

## Context and Problem Statement

Operators self-host on their own Linux server and domain.

## Decision Drivers

* Automatic HTTPS
* Simple install
* No orchestration platform

## Considered Options

* Docker Compose + Caddy (systemd alternative)
* Kubernetes
* Bare app without reverse proxy

## Decision Outcome

Chosen option: "Docker Compose + Caddy (systemd alternative)", because it gives automatic TLS and simple operations.

### Consequences

* Good, because healthcheck, volumes for DB and media
* Bad, because single host — no HA
* Bad, because only Docker Compose is tested and supported; systemd stays a documented option without guarantee

### Confirmation

Deployment smoke test; backup/restore drill.

## More Information

Amended by [ADR-0066](0066-single-container-image.md): a single-container image beside Compose, for an orchestrator such as Kubernetes behind an ingress.

[../../deployment.md](../../deployment.md).

Source: Consolidated spec v1.0 (rounds 1–5, clarifications 45–47)
